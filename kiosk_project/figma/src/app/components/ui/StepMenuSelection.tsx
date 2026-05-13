import { MenuCard } from "../MenuCard";
import type { MenuItem } from "../../hooks/useOrder";

interface StepMenuSelectionProps {
  title: string;
  items: MenuItem[];
  selectedMain?: string | null;
  selectedSides?: Set<string>;
  step: "main" | "side";
  onSelect: (id: string) => void;
  isEmpty?: boolean;
}

export const StepMenuSelection = ({
  title,
  items,
  selectedMain,
  selectedSides,
  step,
  onSelect,
  isEmpty,
}: StepMenuSelectionProps) => {
  return (
    <div className="landscape:flex-1 landscape:overflow-auto">
      <h2 className="text-lg landscape:text-xl font-bold mb-4 landscape:mb-6">
        {title}
      </h2>

      {isEmpty ? (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <p className="text-base landscape:text-lg text-gray-500 mb-2">
              선택 가능한 {step === "main" ? "메인 메뉴" : "사이드"}가 없습니다
            </p>
            <p className="text-sm landscape:text-base text-gray-400">
              {step === "main"
                ? "다음 버튼을 눌러 사이드 선택으로 넘어가세요"
                : "주문을 완료해주세요"}
            </p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 landscape:grid-cols-2 gap-4 landscape:gap-4 landscape:pb-4">
          {items.map((item) => (
            <MenuCard
              key={item.id}
              name={item.name}
              price={item.price}
              image={item.image}
              description={item.description}
              selected={
                step === "main"
                  ? selectedMain === item.id
                  : selectedSides?.has(item.id) || false
              }
              isAvailable={item.isAvailable}
              onClick={() => onSelect(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};
