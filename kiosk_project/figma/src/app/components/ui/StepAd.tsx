import { UtensilsCrossed } from "lucide-react";

interface StepAdProps {
  onStart: () => void;
}

export const StepAd = ({ onStart }: StepAdProps) => {
  return (
    <div className="size-full relative flex items-center justify-center p-4">
      {/* 배경 이미지 */}
      <div className="absolute inset-0">
        <img
          src="https://images.unsplash.com/photo-1596463059283-da257325bab8?w=1200"
          alt="도시락"
          className="w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-black/50 to-black/60" />
      </div>

      {/* 컨텐츠 */}
      <div className="relative text-center w-full z-10">
        <div className="mb-8 landscape:mb-12">
          <div className="bg-white rounded-full w-24 h-24 landscape:w-32 landscape:h-32 flex items-center justify-center mx-auto mb-6 landscape:mb-8 shadow-2xl">
            <UtensilsCrossed className="w-14 h-14 landscape:w-20 landscape:h-20 text-orange-500" />
          </div>
          <h1 className="text-4xl landscape:text-6xl font-bold text-white mb-4 landscape:mb-6 drop-shadow-lg">
            나만의 도련님 도시락
          </h1>
          <p className="text-lg landscape:text-2xl text-white/90 mb-2 landscape:mb-4 drop-shadow-md">
            원하는 메뉴를 골라 나만의 도시락을 만들어보세요
          </p>
          <p className="text-base landscape:text-xl text-white/80 drop-shadow-md">
            신선한 재료로 건강하게!
          </p>
        </div>

        <div className="flex justify-center mt-8 landscape:mt-12">
          <button
            onClick={onStart}
            className="bg-white text-gray-800 rounded-2xl py-8 landscape:py-10 px-12 landscape:px-16 text-xl landscape:text-2xl font-bold hover:bg-gray-100 transition-all shadow-2xl active:scale-95 transform w-full max-w-xs landscape:max-w-md"
          >
            <div className="text-5xl landscape:text-6xl mb-3 landscape:mb-4">
              🍱
            </div>
            주문하기
            <div className="text-sm landscape:text-base font-normal text-gray-600 mt-2">
              새로운 도시락 주문
            </div>
          </button>
        </div>
      </div>
    </div>
  );
};
