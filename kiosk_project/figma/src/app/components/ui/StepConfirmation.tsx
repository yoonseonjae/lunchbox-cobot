import { Check } from "lucide-react";
import { CircularProgress } from "../CircularProgress";

interface StepConfirmationProps {
  realStatus: string;
  orderStage: number;
  isError: boolean;
  pickupNumber: number;
  onReset: () => void;
}

export const StepConfirmation = ({
  realStatus,
  orderStage,
  isError,
  pickupNumber,
  onReset,
}: StepConfirmationProps) => {
  const orderStages = [
    { label: "준비", icon: "🍽️" },
    { label: "반찬", icon: "🍱" },
    { label: "밥", icon: "🍚" },
    { label: "마무리", icon: "🦾" },
  ];

  // 🚨 에러 발생 시 UI (빨간색 경고창)
  if (isError) {
    return (
      <div className="size-full bg-gradient-to-br from-red-500 to-red-700 flex items-center justify-center">
        <div className="bg-white rounded-3xl p-12 text-center shadow-2xl max-w-2xl">
          <div className="bg-red-100 rounded-full w-32 h-32 flex items-center justify-center mx-auto mb-8">
            <span className="text-6xl">🚨</span>
          </div>
          <h2 className="text-4xl font-bold mb-4 text-red-600">로봇 시스템 에러</h2>
          <p className="text-xl text-gray-700 mb-8">
            조리 중 물리적인 충돌이나 오류가 감지되었습니다.<br />
            관리자에게 문의해주세요.
          </p>
          <button
            onClick={onReset}
            className="bg-red-500 text-white rounded-2xl py-4 px-8 text-xl font-bold hover:bg-red-600 transition-colors"
          >
            처음으로 돌아가기
          </button>
        </div>
      </div>
    );
  }

  // ✅ 주문 완료 시 UI
  if (realStatus === "completed") {
    return (
      <div className="size-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
        <div className="bg-white rounded-3xl p-12 text-center shadow-2xl max-w-2xl">
          <div className="bg-green-500 rounded-full w-32 h-32 flex items-center justify-center mx-auto mb-8">
            <Check className="w-20 h-20 text-white" strokeWidth={3} />
          </div>
          <h2 className="text-4xl font-bold mb-4">맛있게 드세요!</h2>
          <div className="bg-blue-50 rounded-2xl p-8 mt-8">
            <p className="text-5xl font-bold text-blue-600 mb-2">{pickupNumber}번</p>
            <p className="text-2xl text-gray-700">배식구에서 찾아가세요</p>
          </div>
        </div>
      </div>
    );
  }

  // ⏳ 로봇 작업 진행 중 UI
  return (
    <div className="size-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
      <div className="bg-white rounded-3xl p-12 text-center shadow-2xl max-w-2xl w-full mx-8">
        <h2 className="text-3xl font-bold mb-8">로봇 조리 중 🦾</h2>

        {/* 중앙 상태 텍스트 표시 영역 */}
        <div className="flex justify-center mb-8">
          <div className="relative">
            <CircularProgress
              progress={Math.min((orderStage + 1) * 25, 95)}
              size={240}
              strokeWidth={16}
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center px-4">
                <div className="text-4xl mb-2">
                  {orderStages[Math.min(orderStage, 3)].icon}
                </div>
                <div className="text-xl font-bold text-blue-600 break-keep">
                  {realStatus}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 하단 단계 인디케이터 */}
        <div className="flex justify-between items-center max-w-xl mx-auto mt-12">
          {orderStages.map((stage, index) => (
            <div key={index} className="flex flex-col items-center flex-1">
              <div
                className={`w-14 h-14 rounded-full flex items-center justify-center mb-3 transition-all duration-500 shadow-md ${
                  index < orderStage
                    ? "bg-green-500 text-white transform scale-110"
                    : index === orderStage
                      ? "bg-blue-500 text-white animate-pulse transform scale-110"
                      : "bg-gray-100 text-gray-400"
                }`}
              >
                {index < orderStage ? (
                  <Check className="w-6 h-6" />
                ) : (
                  <span className="text-2xl">{stage.icon}</span>
                )}
              </div>
              <p
                className={`text-sm font-bold text-center ${
                  index <= orderStage ? "text-gray-800" : "text-gray-400"
                }`}
              >
                {stage.label}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
