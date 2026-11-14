import { createContext, useContext } from "react";
import type { DataSource } from "./source";

export const SourceContext = createContext<DataSource | null>(null);
export function useSource() {
  const source = useContext(SourceContext);
  if (!source) throw new Error("Data source provider is missing");
  return source;
}
