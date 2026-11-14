import { createContext, useContext } from "react";
import type { Region } from "./models";
export const RegionContext = createContext<{
  region: Region;
  setRegion: (region: Region) => void;
  setScope: (region: Region | null, segmentId?: string) => void;
  selectedRegion: Region | null;
  subregionId?: string;
  setSubregion: (id?: string) => void;
  clearRegion: () => void;
}>({
  region: "MUNTENIA",
  setRegion: () => undefined,
  setScope: () => undefined,
  selectedRegion: null,
  setSubregion: () => undefined,
  clearRegion: () => undefined,
});
export const useRegion = () => useContext(RegionContext);
