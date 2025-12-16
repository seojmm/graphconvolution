import Image from "next/image";
import Link from "next/link";
import React, { useState } from "react";

export type PlaceInfo = {
	name: string;
	address: string;
	hours: string;
	tags: string[];
	uri: string;
};

export const PLACES: ReadonlyArray<PlaceInfo> = [
	{
		name: "안녕숯불",
		address: "서울 강남구 테헤란로4길 31",
		hours: "이번 주 금 영업시간 10:30-21:00",
		tags: ["숯불고기", "셀프바", "단체석"],
		uri: "636541662",
	},
	{
		name: "서진식당",
		address: "서울 강남구 강남대로84길 33",
		hours: "이번 주 금 영업시간 10:00-20:00",
		tags: ["보쌈 정식", "김치찜", "단체석"],
		uri: "27504286",
	},
	{
		name: "르뱅돈까스",
		address: "서울 강남구 테헤란로 124",
		hours: "이번 주 금 영업시간 11:00-20:00",
		tags: ["돈까스", "정식", "혼밥"],
		uri: "",
	},
	{
		name: "강남반상 강남역점",
		address: "서울 서초구 서초대로77길 7",
		hours: "이번 주 금 영업시간 10:40-14:30",
		tags: ["한식뷔페", "장국밥", "예산친화"],
		uri: "",
	},
	{
		name: "닭터슐 강남본점",
		address: "서울 강남구 언주로133길 17",
		hours: "이번 주 금 영업시간 11:00-01:00",
		tags: ["초계국수", "닭요리", "프라이빗룸"],
		uri: "",
	},
	{
		name: "감성타코 강남역점",
		address: "서울 강남구 봉은사로 406",
		hours: "이번 주 금 영업시간 13:00-22:00",
		tags: ["멕시칸", "데이트", "단체석"],
		uri: "",
	},
	{
		name: "딘타이펑 강남점",
		address: "서울 서초구 서초대로77길 12",
		hours: "이번 주 금 영업시간 11:00-22:00",
		tags: ["샤오롱바오", "중식", "프라이빗룸"],
		uri: "8279464",
	},
	{
		name: "인더비엣 신논현역점",
		address: "서울 서초구 서초대로55길 13",
		hours: "이번 주 금 영업시간 11:00-21:00",
		tags: ["동남아 감성", "쌀국수", "단체석"],
		uri: "382817114",
	},
	{
		name: "강남버섯칼국수",
		address: "서울 서초구 서래로7길 23",
		hours: "이번 주 금 영업시간 11:00-22:00",
		tags: ["세트", "튀김", "프라이빗룸"],
		uri: "",
	},
	{
		name: "마라공방 강남역점",
		address: "서울 강남구 강남대로94길 20",
		hours: "이번 주 금 영업시간 11:00-22:00",
		tags: ["마라탕", "중식", "단체석"],
		uri: "",
	},
];

export const CAFES: ReadonlyArray<PlaceInfo> = [
	{
		name: "듀자미",
		address: "서울 강남구 도산대로11길 28",
		hours: "오늘 영업시간 12:00-21:00",
		tags: ["케이크", "수요미식회", "테라스"],
		uri: "12983903",
	},
	{
		name: "따우전드 신사점",
		address: "서울 강남구 강남대로162길 36",
		hours: "오늘 영업시간 12:00-22:00",
		tags: ["바나나크림파이", "크리스마스", "테라스"],
		uri: "1363607100",
	},
	{
		name: "쿠라우니",
		address: "서울 강남구 강남대로156길 39",
		hours: "오늘 영업시간 11:00-22:00",
		tags: ["브라우니", "크리스마스 분위기"],
		uri: "1336193965",
	},
	{
		name: "크림라벨 신사점",
		address: "서울 강남구 강남대로154길 37",
		hours: "오늘 영업시간 11:00-19:00",
		tags: ["무화과 케이크", "크리스마스", "데이트"],
		uri: "104127937",
	},
	{
		name: "홍만당",
		address: "서울 강남구 혼현로159길 47",
		hours: "오늘 영업시간 12:00-20:00",
		tags: ["딸기 앙찌", "청포도 앙찌", "찹쌀떡"],
		uri: "1438993234",
	},
	{
		name: "스타벅스 신사가로수점",
		address: "서울 강남구 가로수길 59",
		hours: "오늘 영업시간 08:00-21:00",
		tags: ["가로수길", "라떼", "단체석"],
		uri: "882114256",
	},
	{
		name: "르브런치",
		address: "서울 강남구 도산대로23길 24",
		hours: "오늘 영업시간 10:00-20:00",
		tags: ["딸기쇼트", "브런치", "여유로운"],
		uri: "",
	},
	{
		name: "엠브로시아",
		address: "서울 서초구 사평대로53길 10",
		hours: "오늘 영업시간 11:00-22:00",
		tags: ["말차티라미수", "티바", "조용한"],
		uri: "",
	},
	{
		name: "라이트하우스 커피",
		address: "서울 강남구 봉은사로51길 12",
		hours: "오늘 영업시간 09:00-22:00",
		tags: ["말차라떼", "라떼아트", "루프탑"],
		uri: "",
	},
	{
		name: "테이크어브레드",
		address: "서울 강남구 압구정로29길 32",
		hours: "오늘 영업시간 10:00-21:00",
		tags: ["크루아상", "딸기크림", "베이커리"],
		uri: "",
	},
];

const buildMapUrl = (name: string, uri: string) =>
	`https://place.map.kakao.com/${uri}`;

type Total10Props = {
	onSelect?: (place: PlaceInfo) => void;
	onExpandToggle?: (expanded: boolean) => void;
	reverseOrder?: boolean;
	items?: ReadonlyArray<PlaceInfo>;
};

const Total10 = ({
	onSelect,
	onExpandToggle,
	reverseOrder = false,
	items,
}: Total10Props) => {
	const [expanded, setExpanded] = useState(false);
	const source = items ?? PLACES;
	const orderedPlaces = !reverseOrder ? [...source].reverse() : source;
	const visiblePlaces = expanded ? orderedPlaces : orderedPlaces.slice(0, 3);

	const handleKeySelection = (
		event: React.KeyboardEvent<HTMLDivElement>,
		place: PlaceInfo
	) => {
		if (!onSelect) return;
		if (event.key === "Enter" || event.key === " ") {
			event.preventDefault();
			onSelect(place);
		}
	};

	const listClasses = expanded
		? "flex flex-col gap-3 overflow-y-auto pr-1 max-h-[420px]"
		: "flex flex-col gap-3";

	return (
		<div className="w-full text-sm text-gray-900">
			<div className={listClasses}>
				{visiblePlaces.map((place) => {
					const mapUrl = buildMapUrl(place.name, place.uri);
					return (
						<div
							key={place.name}
							role={onSelect ? "button" : undefined}
							tabIndex={onSelect ? 0 : undefined}
							onClick={() => onSelect?.(place)}
							onKeyDown={(event) => handleKeySelection(event, place)}
							className={`rounded-2xl bg-white p-3 shadow-sm transition ${
								onSelect
									? "cursor-pointer hover:shadow-md focus-visible:outline focus-visible:outline-[#1f1f1f]"
									: ""
							}`}
						>
							<div className="flex items-start justify-between gap-4">
								<div className="flex-1">
									<div className="flex items-center gap-1">
										<span className="text-sm font-semibold text-gray-900">
											{place.name}
										</span>
										<Link
											href={mapUrl}
											target="_blank"
											rel="noopener noreferrer"
											onClick={(event) => event.stopPropagation()}
											className="inline-flex items-center justify-center transition hover:border-[#fee500] hover:bg-[#fff9cc]"
										>
											<Image
												src="/assets/kakaomap_basic.png"
												alt="KakaoMap"
												width={14}
												height={14}
											/>
											<span className="sr-only">{`${place.name} 카카오맵으로 열기`}</span>
										</Link>
									</div>
									<div className="text-[10px] text-gray-500">
										{place.address}
									</div>
									<div className="text-[11px] text-gray-600">{place.hours}</div>
								</div>
								<div className="flex flex-col items-end gap-1 text-right text-[11px] font-medium text-gray-700">
									{place.tags.map((tag) => (
										<span key={tag}>{tag}</span>
									))}
								</div>
							</div>
						</div>
					);
				})}
			</div>
			{source.length > 3 && (
				<button
					type="button"
					onClick={() =>
						setExpanded((prev) => {
							const next = !prev;
							onExpandToggle?.(next);
							return next;
						})
					}
					className="mx-auto mt-4 block text-xs font-semibold text-gray-500 underline decoration-dotted"
				>
					{expanded ? "접기" : "더보기"}
				</button>
			)}
		</div>
	);
};

export default Total10;
