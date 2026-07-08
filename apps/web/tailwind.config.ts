import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          blue: "#1d4ed8",
          black: "#111827"
        },
        paper: "#fbfbf8",
        wash: "#eef6f4",
        signal: "#c7f36b"
      },
      boxShadow: {
        sheet: "0 20px 70px rgba(15, 23, 42, 0.10)"
      }
    }
  },
  plugins: []
};

export default config;
