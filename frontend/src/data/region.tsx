import { useState } from "react";
import type { PropsWithChildren } from "react";
import { RegionContext } from "./region-context";
import type { Region } from "./models";

export function RegionProvider({ children }: PropsWithChildren) {
  const [region, setRegion] = useState<Region>("MUNTENIA");
  return (
    <RegionContext.Provider value={{ region, setRegion }}>
      {children}
    </RegionContext.Provider>
  );
}
