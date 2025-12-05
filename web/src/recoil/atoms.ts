import {atom} from "recoil";
import {recoilPersist} from "recoil-persist";

const sessionStorage =
	typeof window !== "undefined" ? window.sessionStorage : undefined;

const { persistAtom } = recoilPersist({
	key: "recoilpersist",
	storage: sessionStorage,
});

export const activeTabState = atom({
  key: "activeTabState",
  default: [],
  effects_UNSTABLE: [persistAtom],
});