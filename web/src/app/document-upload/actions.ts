"use server";

import {
  ApiError,
  ConfigurationError,
  uploadDocument,
  type UploadDocumentRole,
} from "@/lib/procurement-api";

export type UploadState = {
  error?: string;
  documentId?: string;
  filename?: string;
  sha256?: string;
  extractionStatus?: "PASS" | "FAIL" | "UNKNOWN";
  extractionReasons?: string[];
};

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const SUPPORTED_EXTENSIONS = /\.(pdf|docx|xlsx)$/i;

async function submitDocument(form: FormData, role: UploadDocumentRole): Promise<UploadState> {
  const supplied = [...form.entries()].filter(([name]) => !name.startsWith("$ACTION_"));
  if (supplied.length !== 1 || supplied[0][0] !== "file") {
    return { error: "Выберите ровно один документ." };
  }
  const file = supplied[0][1];
  if (!(file instanceof File) || !file.size || file.size > MAX_UPLOAD_BYTES) {
    return { error: "Файл должен быть непустым и не больше 20 МиБ." };
  }
  if (
    !file.name ||
    file.name.length > 255 ||
    /[/\\\0]/.test(file.name) ||
    !SUPPORTED_EXTENSIONS.test(file.name)
  ) {
    return { error: "Поддерживаются файлы PDF, DOCX и XLSX с обычным именем." };
  }
  try {
    const result = await uploadDocument(file, role);
    if (result.document_role !== role) {
      return { error: "API вернул документ с другой ролью. Загрузка требует проверки." };
    }
    return {
      documentId: result.document_id,
      filename: result.original_filename,
      sha256: result.sha256,
      extractionStatus: result.extraction.status,
      extractionReasons: result.extraction.reasons,
    };
  } catch (error) {
    if (error instanceof ConfigurationError) {
      return { error: "Серверный доступ к API не настроен." };
    }
    if (error instanceof ApiError) {
      if (error.status === 413) return { error: "Файл превышает лимит API." };
      if (error.status === 415 || error.status === 422) {
        return { error: "API отклонил формат или содержимое документа." };
      }
      if (error.status === 403) return { error: "Недостаточно прав для загрузки." };
      return { error: `API не сохранил документ (HTTP ${error.status}).` };
    }
    return { error: "Загрузка не завершилась. Проверьте соединение с API." };
  }
}

export async function uploadTenderDocument(_: UploadState, form: FormData): Promise<UploadState> {
  return submitDocument(form, "TENDER_REQUIREMENTS");
}

export async function uploadSupplierQuote(_: UploadState, form: FormData): Promise<UploadState> {
  return submitDocument(form, "SUPPLIER_QUOTE");
}

export async function uploadApplicationAttachment(
  _: UploadState,
  form: FormData,
): Promise<UploadState> {
  return submitDocument(form, "APPLICATION_ATTACHMENT");
}
