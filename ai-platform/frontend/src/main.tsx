import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

/**
 * React application entry point.
 *
 * Mounts the root <App /> component with BrowserRouter enabled for
 * client-side routing. The entire application is wrapped in StrictMode
 * to surface potential problems during development.
 */
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
