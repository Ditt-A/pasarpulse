import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}", "./stores/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#07111f",
        panel: "#0d1a2b",
        line: "#20334a",
        cyanpulse: "#62d6e8",
        amberpulse: "#f6bd60",
        highpulse: "#f07470",
      },
      boxShadow: { panel: "0 16px 40px rgba(0,0,0,.18)" },
    },
  },
  plugins: [],
};

export default config;
