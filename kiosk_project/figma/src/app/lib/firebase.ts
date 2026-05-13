import { initializeApp } from "firebase/app";
import {
  getFirestore,
  collection,
  addDoc,
  serverTimestamp,
  doc,
  onSnapshot,
} from "firebase/firestore";
import { getDatabase, ref, onValue } from "firebase/database";

const firebaseConfig = {
  apiKey: "AIzaSyC_NZOE-Ck22CmM79fUFso0Ni12tOXGJMk",
  authDomain: "rokey-d3991.firebaseapp.com",
  databaseURL: "https://rokey-d3991-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "rokey-d3991",
  storageBucket: "rokey-d3991.firebasestorage.app",
  messagingSenderId: "748373395576",
  appId: "1:748373395576:web:6b16799234ce6f115bc58d",
};

// Firebase 초기화
const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);
export const rtdb = getDatabase(app);

// 주문 제출 함수
export const submitOrder = async (
  items: Array<{ id: string; name: string; price: number; quantity: number }>,
) => {
  try {
    const orderData = {
      items,
      total_price: items.reduce((acc, item) => acc + item.price, 0),
      status: "pending",
      created_at: serverTimestamp(),
      user_name: "고객",
    };

    const docRef = await addDoc(collection(db, "orders"), orderData);
    return docRef.id;
  } catch (error) {
    console.error("Error adding document: ", error);
    throw error;
  }
};

// Firestore 주문 상태 감시
export const watchOrderStatus = (
  orderId: string,
  onUpdate: (status: string) => void,
  onError: (error: boolean) => void,
) => {
  return onSnapshot(doc(db, "orders", orderId), (docSnap) => {
    if (docSnap.exists()) {
      const status = docSnap.data().status;

      if (status === "error") {
        onError(true);
      } else if (status === "completed") {
        onUpdate("completed");
      }
    }
  });
};

// Realtime Database 로봇 상태 감시
export const watchRobotStatus = (
  onStepChange: (step: number, status: string) => void,
) => {
  const rtdbRef = ref(rtdb, "robot_status");

  return onValue(rtdbRef, (snapshot) => {
    const data = snapshot.val();

    if (
      data?.step_log &&
      Array.isArray(data.step_log) &&
      data.step_log.length > 0
    ) {
      const latestLog = data.step_log[data.step_log.length - 1];

      const match = latestLog.match(/\[(\d)\/5\]/);

      if (match) {
        const stepNum = parseInt(match[1], 10);

        switch (stepNum) {
          case 1:
            onStepChange(0, "식판 준비");
            break;
          case 2:
          case 3:
            onStepChange(1, "반찬 준비");
            break;
          case 4:
            onStepChange(2, "밥 담기");
            break;
          case 5:
            onStepChange(3, "픽업장소 이동");
            break;
          default:
            break;
        }
      } else {
        if (latestLog.includes("🎉 주문 완료!")) {
          onStepChange(4, "completed");
        } else if (latestLog.includes("🔄 🥗 [김치] 홈 이동")) {
          onStepChange(1, "반찬 준비");
        }
      }
    }
  });
};
