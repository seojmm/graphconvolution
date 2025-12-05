"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { BsBatteryFull } from "react-icons/bs";

const TopBar = () => {
  const pathname = usePathname();
  if (pathname === "/") return null;

  return (
    <>
      <div
        className="absolute inset-x-36 top-3 h-6 rounded-full bg-black"
        aria-hidden
      />
      <div className="flex items-center justify-between text-s relative top-2 px-6">
        <span className="font-semibold">18:25</span>
        <div className="flex items-center gap-1.5 text-sm" aria-hidden>
          <div className="flex flex-row items-end gap-0.5">
            <span className="block w-1 h-[3px] bg-black rounded-sm" />
            <span className="block w-1 h-[6px] bg-black rounded-sm" />
            <span className="block w-1 h-[9px] bg-black rounded-sm" />
            <span className="block w-1 h-[12px] bg-black rounded-sm" />
          </div>
          <span className="font-semibold">5G</span>
          <BsBatteryFull size={28} />
        </div>
      </div>
    </>
  );
};

export default TopBar;
