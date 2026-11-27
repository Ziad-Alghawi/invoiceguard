/** Where a field's value is printed in the PDF, as the API found it in the text layer. */

/** A box on one page, in fractions of the page size with the origin at the top left. */
export type Highlight = {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

function percent(value: number): string {
  return `${(Math.min(Math.max(value, 0), 1) * 100).toFixed(3)}%`;
}

/** CSS for a box drawn over its page; works at any rendered width. */
export function highlightStyle(box: Highlight): React.CSSProperties {
  return {
    left: percent(box.x0),
    top: percent(box.y0),
    width: percent(box.x1 - box.x0),
    height: percent(box.y1 - box.y0),
  };
}
