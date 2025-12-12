"use client"

import { useState } from "react";
import { usePathname } from "next/navigation";
import { BsFillPersonFill, BsChatFill, BsThreeDots } from "react-icons/bs";
import { IoChatbubbles } from "react-icons/io5";
import { GiShoppingBag } from "react-icons/gi";
import { ActiveTab } from "../../../types/activeTab";
import Link from "next/link";

const tabBarItems = [
  { label: "프로필", icon: <BsFillPersonFill size={28} /> },
  { label: "채팅", icon: <BsChatFill size={24} /> },
  { label: "지금", icon: <IoChatbubbles size={24} /> },
  { label: "쇼핑", icon: <GiShoppingBag size={24} /> },
  { label: "더보기", icon: <BsThreeDots size={24} /> },
];

const Footer = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>(tabBarItems[1]);
  const pathname = usePathname();

  if (pathname === "/") return null;

  return (
    <footer className="absolute bottom-0 h-16 w-full border-t flex flex-row px-8 text-xs justify-between text-gray-700 pt-1">
        {/* <Link href="/" className="items-center focus:outline-none">
          <span
              className={`w-10 h-10 flex items-center justify-center ${
                  activeTab.label === "프로필"
                  ? "text-[#565656]"
                  : "text-gray-400"
              }`}
              >
              {activeTab.icon}
              </span>
        </Link>
        <Link href="/chat" className="items-center focus:outline-none">
          <span
              className={`w-10 h-10 flex items-center justify-center ${
                  activeTab.label === "채팅"
                  ? "text-[#565656]"
                  : "text-gray-400"
              }`}
              >
              {activeTab.icon}
              </span>
        </Link>
        <Link href="/" className="items-center focus:outline-none">
          <span
              className={`w-10 h-10 flex items-center justify-center ${
                  activeTab.label === "지금"
                  ? "text-[#565656]"
                  : "text-gray-400"
              }`}
              >
              {activeTab.icon}
              </span>
        </Link>
        <Link href="/" className="items-center focus:outline-none">
          <span
              className={`w-10 h-10 flex items-center justify-center ${
                  activeTab.label === "쇼핑"
                  ? "text-[#565656]"
                  : "text-gray-400"
              }`}
              >
              {activeTab.icon}
              </span>
        </Link>
        <Link href="/" className="items-center focus:outline-none">
          <span
              className={`w-10 h-10 flex items-center justify-center ${
                  activeTab.label === "더보기"
                  ? "text-[#565656]"
                  : "text-gray-400"
              }`}
              >
              {activeTab.icon}
              </span>
        </Link> */}

    </footer>
  )
}

export default Footer
