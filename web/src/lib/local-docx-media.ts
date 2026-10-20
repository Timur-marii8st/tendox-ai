const EOCD_SIGNATURE = 0x06054b50;
const CENTRAL_FILE_SIGNATURE = 0x02014b50;
const LOCAL_FILE_SIGNATURE = 0x04034b50;
const MAX_EOCD_SEARCH = 65_557;
const MAX_ENTRIES = 4_096;
const MAX_MEDIA_BYTES = 20 * 1024 * 1024;

export class LocalDocxError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "LocalDocxError";
  }
}

type CentralEntry = {
  compressedSize: number;
  flags: number;
  localHeaderOffset: number;
  method: number;
  name: string;
  uncompressedSize: number;
};

/** Extract one exact OOXML ZIP member without uploading the DOCX. */
export async function extractLocalDocxMedia(
  source: ArrayBuffer,
  expectedPath: string,
): Promise<Uint8Array<ArrayBuffer>> {
  if (!isSafeMediaPath(expectedPath)) {
    throw new LocalDocxError("UNSAFE_MEDIA_PATH");
  }
  const view = new DataView(source);
  const endOffset = findEndOfCentralDirectory(view);
  const diskNumber = readUint16(view, endOffset + 4);
  const centralDisk = readUint16(view, endOffset + 6);
  const diskEntries = readUint16(view, endOffset + 8);
  const totalEntries = readUint16(view, endOffset + 10);
  const centralSize = readUint32(view, endOffset + 12);
  const centralOffset = readUint32(view, endOffset + 16);

  if (diskNumber !== 0 || centralDisk !== 0 || diskEntries !== totalEntries) {
    throw new LocalDocxError("MULTI_DISK_ZIP_NOT_SUPPORTED");
  }
  if (totalEntries > MAX_ENTRIES) {
    throw new LocalDocxError("ZIP_ENTRY_LIMIT");
  }
  if (centralOffset + centralSize > endOffset) {
    throw new LocalDocxError("INVALID_CENTRAL_DIRECTORY");
  }

  let cursor = centralOffset;
  let match: CentralEntry | null = null;
  for (let index = 0; index < totalEntries; index += 1) {
    ensureRange(view, cursor, 46);
    if (view.getUint32(cursor, true) !== CENTRAL_FILE_SIGNATURE) {
      throw new LocalDocxError("INVALID_CENTRAL_DIRECTORY");
    }
    const flags = readUint16(view, cursor + 8);
    const method = readUint16(view, cursor + 10);
    const compressedSize = readUint32(view, cursor + 20);
    const uncompressedSize = readUint32(view, cursor + 24);
    const nameLength = readUint16(view, cursor + 28);
    const extraLength = readUint16(view, cursor + 30);
    const commentLength = readUint16(view, cursor + 32);
    const localHeaderOffset = readUint32(view, cursor + 42);
    const entrySize = 46 + nameLength + extraLength + commentLength;
    ensureRange(view, cursor, entrySize);
    const name = decodeName(source, cursor + 46, nameLength);

    if (name === expectedPath) {
      if (match) {
        throw new LocalDocxError("DUPLICATE_MEDIA_PATH");
      }
      match = {
        compressedSize,
        flags,
        localHeaderOffset,
        method,
        name,
        uncompressedSize,
      };
    }
    cursor += entrySize;
  }

  if (cursor !== centralOffset + centralSize) {
    throw new LocalDocxError("INVALID_CENTRAL_DIRECTORY");
  }
  if (!match) {
    throw new LocalDocxError("MEDIA_NOT_FOUND");
  }
  return extractEntry(source, view, match);
}

function findEndOfCentralDirectory(view: DataView): number {
  const firstOffset = Math.max(0, view.byteLength - MAX_EOCD_SEARCH);
  for (let offset = view.byteLength - 22; offset >= firstOffset; offset -= 1) {
    if (view.getUint32(offset, true) !== EOCD_SIGNATURE) {
      continue;
    }
    const commentLength = readUint16(view, offset + 20);
    if (offset + 22 + commentLength === view.byteLength) {
      return offset;
    }
  }
  throw new LocalDocxError("INVALID_DOCX_ZIP");
}

async function extractEntry(
  source: ArrayBuffer,
  view: DataView,
  entry: CentralEntry,
): Promise<Uint8Array<ArrayBuffer>> {
  if ((entry.flags & 1) !== 0) {
    throw new LocalDocxError("ENCRYPTED_MEDIA_NOT_SUPPORTED");
  }
  if (entry.uncompressedSize > MAX_MEDIA_BYTES) {
    throw new LocalDocxError("MEDIA_SIZE_LIMIT");
  }
  if (
    entry.compressedSize === 0xffffffff ||
    entry.uncompressedSize === 0xffffffff ||
    entry.localHeaderOffset === 0xffffffff
  ) {
    throw new LocalDocxError("ZIP64_NOT_SUPPORTED");
  }

  const offset = entry.localHeaderOffset;
  ensureRange(view, offset, 30);
  if (view.getUint32(offset, true) !== LOCAL_FILE_SIGNATURE) {
    throw new LocalDocxError("INVALID_LOCAL_HEADER");
  }
  const localNameLength = readUint16(view, offset + 26);
  const localExtraLength = readUint16(view, offset + 28);
  ensureRange(view, offset, 30 + localNameLength + localExtraLength);
  const localName = decodeName(source, offset + 30, localNameLength);
  if (localName !== entry.name) {
    throw new LocalDocxError("MEDIA_PATH_MISMATCH");
  }
  const dataOffset = offset + 30 + localNameLength + localExtraLength;
  ensureRange(view, dataOffset, entry.compressedSize);
  const compressed = source.slice(dataOffset, dataOffset + entry.compressedSize);

  let content: ArrayBuffer;
  if (entry.method === 0) {
    content = compressed;
  } else if (entry.method === 8) {
    try {
      const stream = new Blob([compressed])
        .stream()
        .pipeThrough(new DecompressionStream("deflate-raw"));
      content = await readLimited(stream, entry.uncompressedSize);
    } catch {
      throw new LocalDocxError("MEDIA_DECOMPRESSION_FAILED");
    }
  } else {
    throw new LocalDocxError("UNSUPPORTED_COMPRESSION_METHOD");
  }
  if (content.byteLength !== entry.uncompressedSize) {
    throw new LocalDocxError("MEDIA_SIZE_MISMATCH");
  }
  return new Uint8Array(content);
}

async function readLimited(
  stream: ReadableStream<Uint8Array<ArrayBuffer>>,
  expectedSize: number,
): Promise<ArrayBuffer> {
  const reader = stream.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > expectedSize || total > MAX_MEDIA_BYTES) {
      await reader.cancel();
      throw new LocalDocxError("MEDIA_SIZE_LIMIT");
    }
    chunks.push(value);
  }
  const output = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return output.buffer;
}

function decodeName(source: ArrayBuffer, offset: number, length: number): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(
      new Uint8Array(source, offset, length),
    );
  } catch {
    throw new LocalDocxError("INVALID_ZIP_FILENAME");
  }
}

function ensureRange(view: DataView, offset: number, length: number): void {
  if (offset < 0 || length < 0 || offset + length > view.byteLength) {
    throw new LocalDocxError("TRUNCATED_DOCX_ZIP");
  }
}

function readUint16(view: DataView, offset: number): number {
  ensureRange(view, offset, 2);
  return view.getUint16(offset, true);
}

function readUint32(view: DataView, offset: number): number {
  ensureRange(view, offset, 4);
  return view.getUint32(offset, true);
}

function isSafeMediaPath(value: string): boolean {
  return (
    value.startsWith("word/media/") &&
    !value.includes("\\") &&
    !value.split("/").includes("..")
  );
}
