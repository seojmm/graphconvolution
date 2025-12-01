import type { Metadata } from "next";
import "../../styles/globals.css";
import Providers from "@/app/providers";
import { pretendard } from "../../styles/font";
import { BottomBar } from "@/components/BottomBar";
import TopBar from "@/components/TopBar/TopBar";
import Header from "@/components/Header/Header";
import Footer from "@/components/Footer/Footer";


export const metadata: Metadata = {
  title: "KakaoTalk UI Clone",
  description: "KakaoTalk-inspired UI prototype for feature development",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className={pretendard.className}>
      <body className="bg-[#f1f3f7] text-[#1f1f1f] antialiased items-center justify-center flex min-h-screen">
        <Providers>
          <div className="relative w-[393px] h-[852px] bg-white rounded-[32px] shadow-[0_18px_40px_rgba(0,0,0,0.16)] border border-[#e5e7ea] overflow-hidden">
              <TopBar />
              <Header />
                {children}
              <Footer />
              <BottomBar />
          </div>
        </Providers>
      </body>
    </html>
  );
}
