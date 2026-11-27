"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { type Highlight, highlightStyle } from "@/lib/locations";

type PdfDocument = import("pdfjs-dist").PDFDocumentProxy;

/** Canvas pixels per CSS pixel, capped so a large screen does not render huge pages. */
const MAX_PIXEL_RATIO = 2;

/** Loads pdf.js only in the browser, with its worker, once per page load. */
async function loadPdfJs() {
  const pdfjs = await import("pdfjs-dist");
  if (!pdfjs.GlobalWorkerOptions.workerPort) {
    pdfjs.GlobalWorkerOptions.workerPort = new Worker(
      new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
      { type: "module" },
    );
  }
  return pdfjs;
}

function PdfPage({
  pdf,
  pageNumber,
  highlights,
}: {
  pdf: PdfDocument;
  pageNumber: number;
  highlights: Highlight[];
}) {
  const t = useTranslations("Document");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ratio, setRatio] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    void pdf.getPage(pageNumber).then((page) => {
      const canvas = canvasRef.current;
      if (cancelled || canvas === null) {
        return;
      }
      const base = page.getViewport({ scale: 1 });
      const width = canvas.parentElement?.clientWidth || base.width;
      const pixels = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
      const viewport = page.getViewport({
        scale: (width / base.width) * pixels,
      });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      setRatio(base.height / base.width);
      const render = page.render({ canvas, viewport });
      task = render;
      render.promise.catch(() => undefined);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, pageNumber]);

  const first = highlights[0];
  const markRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [first]);

  return (
    <div
      className="relative w-full border bg-white shadow-sm"
      style={ratio === null ? undefined : { aspectRatio: `1 / ${ratio}` }}
      data-page={pageNumber}
      aria-label={t("page", { page: pageNumber, pages: pdf.numPages })}
      role="img"
    >
      <canvas ref={canvasRef} className="block h-auto w-full" />
      {highlights.map((highlight, index) => (
        <div
          key={`${highlight.x0}-${highlight.y0}`}
          ref={index === 0 ? markRef : undefined}
          data-testid="pdf-highlight"
          className="pointer-events-none absolute rounded-sm bg-yellow-300/40 ring-2 ring-yellow-500"
          style={highlightStyle(highlight)}
        />
      ))}
    </div>
  );
}

/**
 * The invoice PDF drawn with pdf.js, one canvas per page, from the same route as the download.
 * Highlights are drawn over the page as boxes in page fractions, so they fit any width.
 */
export function PdfViewer({
  url,
  highlights,
}: {
  url: string;
  highlights: Highlight[];
}) {
  const t = useTranslations("Document");
  const [pdf, setPdf] = useState<PdfDocument | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let task: { destroy: () => Promise<void> } | null = null;
    void loadPdfJs()
      .then((pdfjs) => {
        // The PDF is untrusted input: no XFA forms; pdf.js runs no document scripts here.
        const loading = pdfjs.getDocument({ url, enableXfa: false });
        task = loading;
        return loading.promise;
      })
      .then((document) => {
        if (!cancelled) {
          setPdf(document);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [url]);

  if (failed) {
    return <p className="text-sm text-destructive">{t("pdfFailed")}</p>;
  }
  if (pdf === null) {
    return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: pdf.numPages }, (_, index) => index + 1).map(
        (pageNumber) => (
          <PdfPage
            key={pageNumber}
            pdf={pdf}
            pageNumber={pageNumber}
            highlights={highlights.filter((box) => box.page === pageNumber)}
          />
        ),
      )}
    </div>
  );
}
