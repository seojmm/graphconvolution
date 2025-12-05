"use client";

import { usePathname } from "next/navigation";

const BottomBar = () => {
  const pathname = usePathname();
  if (pathname === "/") return null;

  return (
    <div
      className="absolute inset-x-32 bottom-2 h-1 rounded-full bg-black"
      aria-hidden
    />
  );
};

export default BottomBar;
