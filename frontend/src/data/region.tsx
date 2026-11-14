import type { PropsWithChildren } from "react";
import { useSearchParams } from "react-router-dom";
import { RegionContext } from "./region-context";
import type { Region } from "./models";
import { readScope, selectScope } from "./scope";

export function RegionProvider({ children }: PropsWithChildren) {
  const [params, setParams] = useSearchParams();
  const { region, selectedRegion, subregionId } = readScope(params);
  const setScope = (value: Region | null, segment?: string) =>
    setParams((previous) => selectScope(previous, value, segment));
  return (
    <RegionContext.Provider
      value={{
        region,
        selectedRegion,
        subregionId,
        setSubregion: (id) => setScope(selectedRegion, id),
        setRegion: (value) => setScope(value),
        setScope,
        clearRegion: () => setScope(null),
      }}
    >
      {children}
    </RegionContext.Provider>
  );
}
