import { useState } from "react";
import type { PropsWithChildren } from "react";
import { RegionContext } from "./region-context";
import type { Region } from "./models";

export function RegionProvider({ children }: PropsWithChildren) {
  const [region, setRegion] = useState<Region>("MUNTENIA");
  const [selectedRegion, selectRegion] = useState<Region | null>(null);
  const [subregionId, setSubregion] = useState<string>();
  return (
    <RegionContext.Provider
      value={{
        region,
        selectedRegion,
        subregionId,
        setSubregion,
        setRegion: (value) => {
          setRegion(value);
          selectRegion(value);
          setSubregion(undefined);
        },
        clearRegion: () => {
          selectRegion(null);
          setSubregion(undefined);
        },
      }}
    >
      {children}
    </RegionContext.Provider>
  );
}
