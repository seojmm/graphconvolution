import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        pretendard: ["var(--font-pretendard)", "system-ui", "sans-serif"],
      },
      colors: {
        kakaoYellow: "#FEE500",
        kakaoGray: "#F6F6F6",
        kakaoInk: "#1F1F1F",
      },
    },
  },
  plugins: [],
};

export default config;
