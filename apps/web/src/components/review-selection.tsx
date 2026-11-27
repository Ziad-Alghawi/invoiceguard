"use client";

import { createContext, useContext, useMemo, useState } from "react";

type Selection = {
  /** The key of the field the reviewer clicked (lib/locations.ts `fieldKey`), or null. */
  selected: string | null;
  select: (key: string | null) => void;
};

const SelectionContext = createContext<Selection>({
  selected: null,
  select: () => undefined,
});

/** Shares the clicked field between the fields table and the document on the other side. */
export function SelectionProvider({ children }: { children: React.ReactNode }) {
  const [selected, select] = useState<string | null>(null);
  const value = useMemo(() => ({ selected, select }), [selected]);
  return (
    <SelectionContext.Provider value={value}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection(): Selection {
  return useContext(SelectionContext);
}
