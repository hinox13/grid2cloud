import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/libre-franklin/latin-500.css";
import "@fontsource/libre-franklin/latin-700.css";
import "@fontsource/source-serif-4/latin-400.css";
import "@fontsource/source-serif-4/latin-400-italic.css";
import "@fontsource/source-serif-4/latin-600.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/home.css";
import "./styles/experience.css";
import "./styles/viz.css";
import "./styles/explorer.css";
import { App } from "./App";
import { ClaimsProvider } from "./data/load";
import { ThemeProvider } from "./components/theme";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ClaimsProvider>
        <App />
      </ClaimsProvider>
    </ThemeProvider>
  </StrictMode>,
);
