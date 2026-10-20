"use client";

import { useEffect, useMemo, useState } from "react";

import { extractLocalDocxMedia, LocalDocxError } from "@/lib/local-docx-media";

const MAX_REVIEW_BYTES = 2 * 1024 * 1024;
const MAX_DOCX_BYTES = 20 * 1024 * 1024;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

type ExpectedLine = { page_number: number; text: string };
type ReviewUncertainty = { region: string; visible_text: string; reason: string };
type CalibrationReview = {
  schema_version: "docx-media-calibration-review-v1";
  review_status: "AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION" | "HUMAN_CONFIRMED";
  reviewer_type: "AI_VISUAL_REVIEW" | "HUMAN";
  reviewed_by: string;
  reviewed_at: string;
  authorization_reference: string;
  source_document: string;
  source_document_sha256: string;
  media_index: number;
  source_media: string;
  source_media_sha256: string;
  image_width: number;
  image_height: number;
  ocr_report_sha256: string | null;
  method: string;
  engine: string;
  minimum_expected_lines: number;
  minimum_recall: number;
  baseline_threshold: number;
  expected: ExpectedLine[];
  uncertainties: ReviewUncertainty[];
  [key: string]: unknown;
};

type LoadedImage = {
  height: number;
  name: string;
  sha256: string;
  url: string;
  width: number;
};

export function OcrReviewWorkspace() {
  const [review, setReview] = useState<CalibrationReview | null>(null);
  const [reviewName, setReviewName] = useState("");
  const [reviewSha256, setReviewSha256] = useState("");
  const [expected, setExpected] = useState<ExpectedLine[]>([]);
  const [resolutions, setResolutions] = useState<string[]>([]);
  const [docxFile, setDocxFile] = useState<File | null>(null);
  const [image, setImage] = useState<LoadedImage | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [confirmedAll, setConfirmedAll] = useState(false);
  const [zoom, setZoom] = useState(15);
  const [reviewError, setReviewError] = useState("");
  const [docxError, setDocxError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    return () => {
      if (image) URL.revokeObjectURL(image.url);
    };
  }, [image]);

  const changedLines = useMemo(() => {
    if (!review) return 0;
    return expected.reduce(
      (count, line, index) => count + (line.text !== review.expected[index]?.text ? 1 : 0),
      0,
    );
  }, [expected, review]);

  const invalidLineCount = expected.filter((line) => !line.text.trim()).length;
  const unresolvedCount = resolutions.filter((value) => !value.trim()).length;
  const evidenceVerified = Boolean(review && image);
  const canDownload = Boolean(
    evidenceVerified &&
      reviewer.trim() &&
      confirmedAll &&
      expected.length >= (review?.minimum_expected_lines ?? Number.POSITIVE_INFINITY) &&
      invalidLineCount === 0 &&
      unresolvedCount === 0,
  );

  async function loadReview(file: File | undefined) {
    setReviewError("");
    setDocxError("");
    setConfirmedAll(false);
    setImage(null);
    if (!file) return;
    if (file.size > MAX_REVIEW_BYTES) {
      setReviewError("Review JSON превышает лимит 2 МБ.");
      return;
    }
    try {
      const bytes = await file.arrayBuffer();
      const parsed: unknown = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(bytes),
      );
      const validated = validateReview(parsed);
      setReview(validated);
      setReviewName(file.name);
      setReviewSha256(await sha256(bytes));
      setExpected(validated.expected.map((line) => ({ ...line })));
      setResolutions(validated.uncertainties.map(() => ""));
      if (docxFile) await verifyDocx(docxFile, validated);
    } catch (error) {
      setReview(null);
      setExpected([]);
      setResolutions([]);
      setReviewError(readableError(error, "Некорректный review JSON."));
    }
  }

  async function loadDocx(file: File | undefined) {
    setDocxError("");
    setImage(null);
    setDocxFile(file ?? null);
    if (!file) return;
    if (!review) {
      setDocxError("DOCX выбран. Теперь выберите AI review JSON — проверка продолжится автоматически.");
      return;
    }
    await verifyDocx(file, review);
  }

  async function verifyDocx(file: File, activeReview: CalibrationReview) {
    setDocxError("");
    setImage(null);
    if (file.size > MAX_DOCX_BYTES) {
      setDocxError("DOCX превышает лимит 20 МБ.");
      return;
    }
    setBusy(true);
    try {
      const bytes = await file.arrayBuffer();
      const documentSha = await sha256(bytes);
      if (documentSha !== activeReview.source_document_sha256) {
        throw new Error("SHA-256 выбранного DOCX не совпадает с review.");
      }
      const media = await extractLocalDocxMedia(bytes, activeReview.source_media);
      const mediaSha = await sha256(media);
      if (mediaSha !== activeReview.source_media_sha256) {
        throw new Error("SHA-256 изображения внутри DOCX не совпадает с review.");
      }
      const blob = new Blob([media], { type: mediaType(activeReview.source_media) });
      const url = URL.createObjectURL(blob);
      const dimensions = await imageDimensions(url);
      if (
        dimensions.width !== activeReview.image_width ||
        dimensions.height !== activeReview.image_height
      ) {
        URL.revokeObjectURL(url);
        throw new Error("Размер изображения внутри DOCX не совпадает с review.");
      }
      setImage({ ...dimensions, name: file.name, sha256: mediaSha, url });
    } catch (error) {
      setDocxError(readableError(error, "Не удалось проверить DOCX."));
    } finally {
      setBusy(false);
    }
  }

  function changeExpected(index: number, text: string) {
    setExpected((current) =>
      current.map((line, lineIndex) =>
        lineIndex === index ? { ...line, text } : line,
      ),
    );
    setConfirmedAll(false);
  }

  function addExpectedLine() {
    setExpected((current) => [...current, { page_number: 1, text: "" }]);
    setConfirmedAll(false);
  }

  function removeExpectedLine(index: number) {
    setExpected((current) => current.filter((_, lineIndex) => lineIndex !== index));
    setConfirmedAll(false);
  }

  function downloadConfirmation() {
    if (!review || !canDownload) return;
    const resolutionEvidence = review.uncertainties
      .map((item, index) => `${item.region}: ${resolutions[index].trim()}`)
      .join("; ");
    const confirmed: CalibrationReview = {
      ...review,
      review_status: "HUMAN_CONFIRMED",
      reviewer_type: "HUMAN",
      reviewed_by: reviewer.trim(),
      reviewed_at: new Date().toISOString(),
      method: [
        review.method.trim(),
        `Human confirmation in the local Syurai review workspace. Parent AI review SHA-256: ${reviewSha256}.`,
        `Resolved uncertainties: ${resolutionEvidence || "none"}.`,
        "The complete expected-line list was visually checked against the immutable DOCX media.",
      ].join(" "),
      expected,
      uncertainties: [],
    };
    const blob = new Blob([`${JSON.stringify(confirmed, null, 2)}\n`], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${reviewName.replace(/\.json$/i, "")}.human-confirmed.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="grid gap-5">
      <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm lg:grid-cols-2 lg:p-5">
        <FileCard
          accept="application/json,.json"
          detail={
            review
              ? `${review.expected.length} строк · ${review.uncertainties.length} неоднозначности`
              : "Сначала выберите AI review JSON"
          }
          error={reviewError}
          id="review-file"
          label="1. AI-разметка"
          onFile={loadReview}
        />
        <FileCard
          accept="application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx"
          detail={
            image
              ? `Проверено: ${image.width}×${image.height} px`
              : docxFile
                ? "DOCX выбран; ожидается или выполняется проверка"
                : "Можно выбрать до или после AI-разметки"
          }
          disabled={busy}
          error={docxError}
          id="docx-file"
          label={busy ? "Проверяю DOCX…" : "2. Исходный DOCX"}
          onFile={loadDocx}
        />
        {review && (
          <div className="col-span-full grid gap-2 rounded-xl bg-slate-50 p-3 text-xs text-slate-600 md:grid-cols-2">
            <Evidence label="AI review SHA-256" value={reviewSha256} />
            <Evidence
              label="Media SHA-256"
              value={review.source_media_sha256}
              verified={Boolean(image)}
            />
          </div>
        )}
      </section>

      {!review ? (
        <section className="rounded-2xl border border-dashed border-slate-300 bg-white/70 p-10 text-center text-slate-600">
          Выберите AI review JSON. После проверки схемы станет доступен исходный DOCX.
        </section>
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(420px,.75fr)]">
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-900 shadow-sm xl:sticky xl:top-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700 px-4 py-3 text-white">
              <div>
                <strong className="text-sm">Исходное изображение</strong>
                <p className="m-0 mt-1 text-xs text-slate-300">
                  {image?.name ?? "DOCX ещё не проверен"}
                </p>
              </div>
              <label className="flex items-center gap-2 text-xs">
                Масштаб {zoom}%
                <input
                  aria-label="Масштаб изображения"
                  className="w-32 accent-blue-500"
                  max="100"
                  min="5"
                  onChange={(event) => setZoom(Number(event.target.value))}
                  type="range"
                  value={zoom}
                />
              </label>
            </div>
            <div className="h-[68vh] min-h-[32rem] overflow-auto bg-slate-800 p-3">
              {image ? (
                // Native img is required for a browser-created object URL with exact pixel zoom.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  alt="Чертёж из проверенного DOCX"
                  className="max-w-none bg-white shadow-2xl"
                  src={image.url}
                  style={{ width: `${Math.max(500, (image.width * zoom) / 100)}px` }}
                />
              ) : (
                <div className="grid h-full place-items-center text-center text-sm text-slate-300">
                  Выберите совпадающий DOCX — изображение будет извлечено локально и сверено по SHA-256.
                </div>
              )}
            </div>
          </section>

          <div className="grid gap-5">
            <section className="rounded-2xl border border-amber-300 bg-amber-50 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="m-0 text-xs font-black uppercase tracking-wider text-amber-800">
                    Сначала разрешите
                  </p>
                  <h2 className="mt-1 text-xl font-black">Неоднозначности</h2>
                </div>
                <span className="rounded-full bg-amber-200 px-3 py-1 text-xs font-black text-amber-900">
                  {unresolvedCount} не решено
                </span>
              </div>
              <div className="mt-4 grid gap-3">
                {review.uncertainties.map((item, index) => (
                  <article
                    className="rounded-xl border border-amber-200 bg-white p-3"
                    key={`${item.region}-${index}`}
                  >
                    <strong className="text-sm">{item.region}</strong>
                    <p className="my-1 text-sm text-slate-800">
                      AI прочитал: {item.visible_text}
                    </p>
                    <p className="m-0 text-xs leading-5 text-slate-500">
                      {item.reason}
                    </p>
                    <label
                      className="mt-3 block text-xs font-bold"
                      htmlFor={`resolution-${index}`}
                    >
                      Ваше точное решение
                    </label>
                    <input
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                      id={`resolution-${index}`}
                      onChange={(event) => {
                        const value = event.target.value;
                        setResolutions((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? value : item,
                          ),
                        );
                        setConfirmedAll(false);
                      }}
                      placeholder="Например: последняя цифра — 5"
                      value={resolutions[index] ?? ""}
                    />
                  </article>
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="m-0 text-xs font-black uppercase tracking-wider text-blue-700">
                    Проверить полностью
                  </p>
                  <h2 className="mt-1 text-xl font-black">Эталонные строки</h2>
                  <p className="m-0 mt-1 text-xs text-slate-500">
                    {expected.length} строк · изменено {changedLines} · пустых {invalidLineCount}
                  </p>
                </div>
                <button
                  className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-bold text-white"
                  onClick={addExpectedLine}
                  type="button"
                >
                  + Добавить строку
                </button>
              </div>
              <ol className="mt-4 grid max-h-[56rem] gap-2 overflow-y-auto pr-1">
                {expected.map((line, index) => (
                  <li
                    className="grid grid-cols-[2.2rem_minmax(0,1fr)_auto] items-start gap-2 rounded-lg bg-slate-50 p-2"
                    key={index}
                  >
                    <span className="pt-2 text-right text-xs font-bold tabular-nums text-slate-400">
                      {index + 1}
                    </span>
                    <textarea
                      aria-label={`Эталонная строка ${index + 1}`}
                      className="min-h-10 resize-y rounded-md border border-slate-300 bg-white px-2 py-2 text-sm leading-5"
                      onChange={(event) => changeExpected(index, event.target.value)}
                      rows={1}
                      value={line.text}
                    />
                    <button
                      aria-label={`Удалить строку ${index + 1}`}
                      className="rounded-md bg-transparent px-2 py-2 text-slate-400 hover:bg-red-50 hover:text-red-700"
                      onClick={() => removeExpectedLine(index)}
                      type="button"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ol>
            </section>

            <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
              <p className="m-0 text-xs font-black uppercase tracking-wider text-blue-700">
                Финальное подтверждение
              </p>
              <label className="mt-3 block text-sm font-bold" htmlFor="reviewer-id">
                Идентификатор проверяющего
              </label>
              <input
                className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2"
                id="reviewer-id"
                onChange={(event) => {
                  setReviewer(event.target.value);
                  setConfirmedAll(false);
                }}
                placeholder="Например: elkgo"
                value={reviewer}
              />
              <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-blue-200 bg-white p-3 text-sm leading-5">
                <input
                  checked={confirmedAll}
                  className="mt-1 size-4 accent-blue-700"
                  disabled={
                    !evidenceVerified || unresolvedCount > 0 || invalidLineCount > 0
                  }
                  onChange={(event) => setConfirmedAll(event.target.checked)}
                  type="checkbox"
                />
                <span>
                  Я визуально сверил все {expected.length} строк с изображением и подтверждаю внесённые исправления.
                </span>
              </label>
              <button
                className="mt-4 w-full rounded-xl bg-blue-700 px-4 py-3 font-black text-white disabled:cursor-not-allowed disabled:opacity-45"
                disabled={!canDownload}
                onClick={downloadConfirmation}
                type="button"
              >
                Скачать HUMAN_CONFIRMED JSON
              </button>
              {!canDownload && (
                <p className="mb-0 mt-3 text-xs leading-5 text-blue-900">
                  Нужны совпадающий DOCX, решения всех неоднозначностей, непустые строки,
                  ID проверяющего и финальная отметка.
                </p>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function FileCard(props: {
  accept: string;
  detail: string;
  disabled?: boolean;
  error: string;
  id: string;
  label: string;
  onFile: (file: File | undefined) => void | Promise<void>;
}) {
  return (
    <div className="rounded-xl border border-slate-200 p-3">
      <label className="block text-sm font-black" htmlFor={props.id}>
        {props.label}
      </label>
      <input
        accept={props.accept}
        className="mt-2 block w-full cursor-pointer rounded-lg border border-slate-300 bg-slate-50 p-2 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-blue-700 file:px-3 file:py-2 file:font-bold file:text-white"
        disabled={props.disabled}
        id={props.id}
        onChange={(event) => void props.onFile(event.target.files?.[0])}
        type="file"
      />
      <p className="mb-0 mt-2 text-xs text-slate-500">{props.detail}</p>
      {props.error && (
        <p className="mb-0 mt-2 text-xs font-bold text-red-700" role="alert">
          {props.error}
        </p>
      )}
    </div>
  );
}

function Evidence(props: { label: string; value: string; verified?: boolean }) {
  return (
    <p className="m-0 min-w-0">
      <span className="font-bold text-slate-800">
        {props.label}
        {props.verified ? " · проверено" : ""}
      </span>
      <code className="mt-1 block overflow-hidden text-ellipsis whitespace-nowrap font-mono">
        {props.value}
      </code>
    </p>
  );
}

function validateReview(value: unknown): CalibrationReview {
  if (!isRecord(value)) throw new Error("Корень review должен быть JSON-объектом.");
  if (value.schema_version !== "docx-media-calibration-review-v1") {
    throw new Error("Неизвестная версия схемы review.");
  }
  if (value.review_status !== "AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION") {
    throw new Error("Для этой страницы нужен AI review, ожидающий человека.");
  }
  if (value.reviewer_type !== "AI_VISUAL_REVIEW") {
    throw new Error("Некорректный provenance AI review.");
  }
  for (const key of [
    "reviewed_by",
    "reviewed_at",
    "authorization_reference",
    "source_document",
    "source_media",
    "method",
    "engine",
  ] as const) {
    if (typeof value[key] !== "string" || !value[key].trim()) {
      throw new Error(`Поле ${key} отсутствует.`);
    }
  }
  for (const key of ["source_document_sha256", "source_media_sha256"] as const) {
    if (typeof value[key] !== "string" || !SHA256_PATTERN.test(value[key])) {
      throw new Error(`Поле ${key} некорректно.`);
    }
  }
  if (
    value.ocr_report_sha256 !== null &&
    (typeof value.ocr_report_sha256 !== "string" ||
      !SHA256_PATTERN.test(value.ocr_report_sha256))
  ) {
    throw new Error("Поле ocr_report_sha256 некорректно.");
  }
  if (!Number.isInteger(value.media_index) || Number(value.media_index) < 0) {
    throw new Error("Поле media_index некорректно.");
  }
  if (
    !Number.isInteger(value.image_width) ||
    Number(value.image_width) < 1 ||
    !Number.isInteger(value.image_height) ||
    Number(value.image_height) < 1
  ) {
    throw new Error("Размеры изображения некорректны.");
  }
  if (
    !Number.isInteger(value.minimum_expected_lines) ||
    Number(value.minimum_expected_lines) < 1
  ) {
    throw new Error("minimum_expected_lines некорректно.");
  }
  if (
    typeof value.minimum_recall !== "number" ||
    value.minimum_recall < 0 ||
    value.minimum_recall > 1
  ) {
    throw new Error("minimum_recall некорректно.");
  }
  if (
    typeof value.baseline_threshold !== "number" ||
    value.baseline_threshold < 0 ||
    value.baseline_threshold > 1
  ) {
    throw new Error("baseline_threshold некорректно.");
  }
  if (
    !Array.isArray(value.expected) ||
    value.expected.length === 0 ||
    !value.expected.every(isExpectedLine)
  ) {
    throw new Error("Список expected некорректен.");
  }
  if (!Array.isArray(value.uncertainties) || !value.uncertainties.every(isUncertainty)) {
    throw new Error("Список uncertainties некорректен.");
  }
  return value as CalibrationReview;
}

function isExpectedLine(value: unknown): value is ExpectedLine {
  return (
    isRecord(value) &&
    value.page_number === 1 &&
    typeof value.text === "string" &&
    Boolean(value.text.trim())
  );
}

function isUncertainty(value: unknown): value is ReviewUncertainty {
  return (
    isRecord(value) &&
    [value.region, value.visible_text, value.reason].every(
      (item) => typeof item === "string" && Boolean(item.trim()),
    )
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function sha256(content: BufferSource): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", content);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function mediaType(path: string): string {
  return path.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg";
}

function imageDimensions(url: string): Promise<{ height: number; width: number }> {
  return new Promise((resolve, reject) => {
    const candidate = new window.Image();
    candidate.onload = () =>
      resolve({ height: candidate.naturalHeight, width: candidate.naturalWidth });
    candidate.onerror = () =>
      reject(new Error("Вложенный файл не является доступным изображением."));
    candidate.src = url;
  });
}

function readableError(error: unknown, fallback: string): string {
  if (error instanceof LocalDocxError) return `DOCX отклонён: ${error.code}.`;
  return error instanceof Error ? error.message : fallback;
}
