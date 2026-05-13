import { allergyList } from "../../hooks/useOrder";

interface StepPreferenceProps {
  isHalal: boolean;
  isVegan: boolean;
  allergies: Set<string>;
  onHalalToggle: () => void;
  onVeganToggle: () => void;
  onAllergyToggle: (allergy: string) => void;
}

export const StepPreference = ({
  isHalal,
  isVegan,
  allergies,
  onHalalToggle,
  onVeganToggle,
  onAllergyToggle,
}: StepPreferenceProps) => {
  return (
    <div className="space-y-4 landscape:space-y-6">
      {/* 식이 선호도 */}
      <div className="bg-white rounded-xl p-4 landscape:p-6 shadow-md">
        <h3 className="text-base landscape:text-lg font-bold mb-3 landscape:mb-4">
          식이 선호도
        </h3>
        <div className="grid grid-cols-2 gap-3 landscape:gap-4">
          <button
            onClick={onHalalToggle}
            className={`p-4 landscape:p-6 rounded-lg border-2 transition-all ${
              isHalal
                ? "border-green-500 bg-green-50"
                : "border-gray-200 bg-white active:border-green-300"
            }`}
          >
            <div className="text-3xl landscape:text-4xl mb-1 landscape:mb-2">
              🕌
            </div>
            <div className="font-bold text-sm landscape:text-base">
              할랄
            </div>
            <div className="text-xs landscape:text-sm text-gray-600">
              Halal
            </div>
          </button>
          <button
            onClick={onVeganToggle}
            className={`p-4 landscape:p-6 rounded-lg border-2 transition-all ${
              isVegan
                ? "border-green-500 bg-green-50"
                : "border-gray-200 bg-white active:border-green-300"
            }`}
          >
            <div className="text-3xl landscape:text-4xl mb-1 landscape:mb-2">
              🌱
            </div>
            <div className="font-bold text-sm landscape:text-base">
              비건
            </div>
            <div className="text-xs landscape:text-sm text-gray-600">
              Vegan
            </div>
          </button>
        </div>
      </div>

      {/* 알레르기 정보 */}
      <div className="bg-white rounded-xl p-4 landscape:p-6 shadow-md">
        <h3 className="text-base landscape:text-lg font-bold mb-3 landscape:mb-4">
          알레르기 정보
        </h3>
        <p className="text-xs landscape:text-sm text-gray-600 mb-3 landscape:mb-4">
          해당되는 알레르기 항목을 모두 선택해주세요
        </p>
        <div className="grid grid-cols-2 landscape:grid-cols-3 gap-2 landscape:gap-3">
          {allergyList.map((allergy) => (
            <button
              key={allergy}
              onClick={() => onAllergyToggle(allergy)}
              className={`p-3 landscape:p-4 rounded-lg border-2 transition-all text-center ${
                allergies.has(allergy)
                  ? "border-red-500 bg-red-50"
                  : "border-gray-200 bg-white active:border-red-300"
              }`}
            >
              <div className="font-semibold text-sm landscape:text-base">
                {allergy}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
