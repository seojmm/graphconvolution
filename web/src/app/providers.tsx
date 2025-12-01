"use client";
import { RecoilRoot } from "recoil";

interface RecoilRootWrapperProps {
	children: React.ReactNode;
}

export default function Providers({
	children,
}: RecoilRootWrapperProps) {
	return <RecoilRoot>{children}</RecoilRoot>;
}