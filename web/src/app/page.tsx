
import { ChatContainer } from "@/containers/Chat";
import { LandingContainer } from "@/containers/Landing";

const chats = [
  {
    name: "민수",
    message: "점심 뭐 먹을래?",
    time: "오후 1:23",
    unread: 2,
  },
  {
    name: "엄마",
    message: "도착하면 연락해",
    time: "오후 12:58",
  },
  {
    name: "Project Team",
    message: "오늘 데모 일정 공유합니다",
    time: "오전 11:40",
    unread: 5,
  },
  {
    name: "혜진",
    message: "ㅎㅎ 알겠어",
    time: "오전 10:10",
  },
  {
    name: "배달의민족",
    message: "주문이 완료되었습니다",
    time: "오전 9:45",
  },
];



export default function Home() {

  return <LandingContainer />;
}
