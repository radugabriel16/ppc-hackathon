import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);
export async function startMockWorker() {
  await worker.start({
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    onUnhandledRequest(request, print) {
      // Map tiles, Vite assets, and external services remain ordinary requests.
      if (new URL(request.url).pathname.startsWith("/api/v1/")) print.error();
    },
  });
}
