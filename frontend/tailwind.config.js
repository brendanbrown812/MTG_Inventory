/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Cormorant Garamond", "Georgia", "serif"],
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        ink: {
          950: "#0a0b0f",
          900: "#0f1118",
          800: "#161a24",
          700: "#1e2433",
        },
        ember: {
          400: "#e8a87c",
          500: "#d4896a",
        },
        arcane: {
          400: "#9b8fd9",
          500: "#7c6fc2",
        },
        mana: {
          w: "#f8f6d8",
          u: "#0e68ab",
          b: "#4a4a4a",
          r: "#d3202a",
          g: "#00733e",
        },
      },
      boxShadow: {
        glow: "0 0 60px -12px rgba(232, 168, 124, 0.25)",
        card: "0 4px 24px rgba(0,0,0,0.45)",
      },
    },
  },
  plugins: [],
};
