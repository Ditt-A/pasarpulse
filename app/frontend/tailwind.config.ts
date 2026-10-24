import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./stores/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#f5f7f2",
        panel: "#ffffff",
        sage: "#edf3e9",
        line: "#dfe6dd",
        cyanpulse: "#285c45",
        amberpulse: "#9a6b24",
        highpulse: "#b34b3e",
      },
      boxShadow: { panel: "0 2px 6px rgba(32,54,43,.025)" },
    },
  },
  plugins: [],
};

export default config;
