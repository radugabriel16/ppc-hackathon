import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { theme } from "./theme";
import { SourceContext } from "./data/context";
import { prepareSource } from "./data/bootstrap";
import { ErrorNotice } from "./components/common";
import { RegionProvider } from "./data/region";
import { AppError } from "./data/errors";
import { ErrorBoundary, Loading } from "./components/common";
import { Authenticated } from "./components/Authenticated";
import { ManagerOnly, Shell } from "./components/Shell";
import { Login } from "./pages/Login";
import { FilesPage } from "./pages/Files";
import { CasesPage } from "./pages/Cases";
import { UploadsPage } from "./pages/Uploads";
import { AdminPage, StatisticsPage } from "./pages/Overview";
import "./styles.css";

const MapPage = lazy(() =>
  import("./pages/Map").then((module) => ({ default: module.MapPage })),
);
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15000,
      retry: (count, error) =>
        count < 2 && !(error instanceof AppError && error.status < 500),
    },
    mutations: { retry: false },
  },
});
const root = ReactDOM.createRoot(document.getElementById("root")!);
prepareSource(import.meta.env)
  .then((source) => {
    root.render(
      <React.StrictMode>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <ErrorBoundary>
            <QueryClientProvider client={queryClient}>
              <SourceContext.Provider value={source}>
                <RegionProvider>
                  <BrowserRouter>
                    <Routes>
                      <Route path="/login" element={<Login />} />
                      <Route element={<Authenticated />}>
                        <Route element={<Shell />}>
                          <Route
                            path="/map"
                            element={
                              <Suspense fallback={<Loading />}>
                                <MapPage />
                              </Suspense>
                            }
                          />
                          <Route path="/files" element={<FilesPage />} />
                          <Route path="/cases" element={<CasesPage />} />
                          <Route path="/uploads" element={<UploadsPage />} />
                          <Route
                            path="/statistics"
                            element={<StatisticsPage />}
                          />
                          <Route
                            path="/admin"
                            element={
                              <ManagerOnly>
                                <AdminPage />
                              </ManagerOnly>
                            }
                          />
                          <Route
                            index
                            element={<Navigate to="/map" replace />}
                          />
                          <Route
                            path="*"
                            element={<Navigate to="/map" replace />}
                          />
                        </Route>
                      </Route>
                    </Routes>
                  </BrowserRouter>
                </RegionProvider>
              </SourceContext.Provider>
            </QueryClientProvider>
          </ErrorBoundary>
        </ThemeProvider>
      </React.StrictMode>,
    );
  })
  .catch((error) =>
    root.render(
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <div style={{ padding: 32 }}>
          <h1>FileGrid could not start</h1>
          <ErrorNotice error={error} />
        </div>
      </ThemeProvider>,
    ),
  );
