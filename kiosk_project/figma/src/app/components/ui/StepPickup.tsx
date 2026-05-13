import { Check } from "lucide-react";

interface StepPickupProps {
  phoneNumber: string;
  onPhoneChange: (phone: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  showPickupNumber: boolean;
  pickupNumber: number;
}

export const StepPickup = ({
  phoneNumber,
  onPhoneChange,
  onSubmit,
  onCancel,
  showPickupNumber,
  pickupNumber,
}: StepPickupProps) => {
  return (
    <div className="size-full bg-gradient-to-br from-blue-400 to-purple-400 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl p-6 landscape:p-8 shadow-2xl w-full max-w-md landscape:max-w-2xl">
        {!showPickupNumber ? (
          <>
            <h2 className="text-2xl landscape:text-3xl font-bold mb-6 landscape:mb-8 text-center">
              픽업 주문 조회
            </h2>
            <p className="text-base landscape:text-lg text-gray-600 mb-6 landscape:mb-8 text-center">
              주문 시 입력한 전화번호를 입력해주세요
            </p>

            <div className="mb-6 landscape:mb-8">
              <label className="block text-sm landscape:text-base font-semibold mb-3 landscape:mb-4 text-gray-700">
                전화번호
              </label>
              <input
                type="tel"
                value={phoneNumber}
                onChange={(e) =>
                  onPhoneChange(
                    e.target.value.replace(/[^0-9]/g, ""),
                  )
                }
                placeholder="01012345678"
                maxLength={11}
                className="w-full px-4 landscape:px-6 py-3 landscape:py-4 text-lg landscape:text-xl border-2 border-gray-300 rounded-xl focus:outline-none focus:border-blue-500 text-center"
              />
            </div>

            <div className="flex gap-3 landscape:gap-4">
              <button
                onClick={onCancel}
                className="flex-1 bg-gray-300 text-gray-700 rounded-xl py-3 landscape:py-4 text-base landscape:text-lg font-bold active:bg-gray-400 transition-colors"
              >
                취소
              </button>
              <button
                onClick={onSubmit}
                disabled={phoneNumber.length < 10}
                className="flex-1 bg-blue-500 text-white rounded-xl py-3 landscape:py-4 text-base landscape:text-lg font-bold active:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                조회하기
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="text-center mb-6 landscape:mb-8">
              <div className="bg-green-500 rounded-full w-20 h-20 landscape:w-24 landscape:h-24 flex items-center justify-center mx-auto mb-4 landscape:mb-6">
                <Check
                  className="w-12 h-12 landscape:w-16 landscape:h-16 text-white"
                  strokeWidth={3}
                />
              </div>
              <h2 className="text-2xl landscape:text-3xl font-bold mb-4 landscape:mb-6">
                주문 확인 완료
              </h2>
            </div>

            <div className="bg-blue-50 rounded-xl p-6 landscape:p-8 mb-6 landscape:mb-8">
              <p className="text-gray-700 text-base landscape:text-lg mb-3 landscape:mb-4">
                픽업 장소
              </p>
              <p className="text-4xl landscape:text-5xl font-bold text-blue-600 mb-2">
                {pickupNumber}번
              </p>
              <p className="text-xl landscape:text-2xl text-gray-700">
                배식구
              </p>
            </div>

            <button
              onClick={onCancel}
              className="w-full bg-blue-500 text-white rounded-xl py-3 landscape:py-4 text-base landscape:text-lg font-bold active:bg-blue-600 transition-colors"
            >
              처음으로
            </button>
          </>
        )}
      </div>
    </div>
  );
};
