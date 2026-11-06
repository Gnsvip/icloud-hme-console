import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import App from "./App";
import "@fontsource-variable/noto-sans-sc";
import "./style.css";
const client = new QueryClient({
  defaultOptions: { queries: { gcTime: 5 * 60 * 1000 } },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <App />
      <Toaster richColors closeButton position="bottom-right" />
    </QueryClientProvider>
  </React.StrictMode>,
);
