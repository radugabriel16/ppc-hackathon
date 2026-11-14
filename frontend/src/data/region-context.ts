import { createContext, useContext } from "react";
import type { Region } from "./models";
export const RegionContext = createContext<{
  region: Region;
  setRegion: (region: Region) => void;
}>({ region: "MUNTENIA", setRegion: () => undefined });
export const useRegion = () => useContext(RegionContext);
