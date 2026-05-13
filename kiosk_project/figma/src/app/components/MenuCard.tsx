import { Check } from 'lucide-react';

interface MenuCardProps {
  name: string;
  price: number;
  image: string;
  description?: string;
  selected: boolean;
  onClick: () => void;
  isAvailable?: boolean;
}

export function MenuCard({ name, price, image, description, selected, onClick, isAvailable = true }: MenuCardProps) {
  return (
    <button
      onClick={isAvailable ? onClick : undefined}
      disabled={!isAvailable}
      className={`relative overflow-hidden rounded-xl transition-all flex items-center ${
        selected
          ? 'ring-4 ring-blue-500 shadow-xl'
          : 'ring-2 ring-gray-200 active:ring-blue-300 shadow-md'
      } ${!isAvailable ? 'opacity-60 cursor-not-allowed' : ''}`}
    >
      <div className="w-28 h-28 landscape:w-32 landscape:h-32 relative flex-shrink-0">
        <img
          src={image}
          alt={name}
          className="w-full h-full object-cover"
        />
        {selected && (
          <div className="absolute inset-0 bg-blue-500/20 flex items-center justify-center">
            <div className="bg-blue-500 rounded-full p-2 landscape:p-2.5">
              <Check className="w-5 h-5 landscape:w-6 landscape:h-6 text-white" strokeWidth={3} />
            </div>
          </div>
        )}
        {!isAvailable && (
          <div className="absolute inset-0 bg-gray-500/70 flex items-center justify-center">
            <div className="bg-white/90 rounded-lg px-4 py-2">
              <p className="font-bold text-gray-800 text-sm landscape:text-base">준비중</p>
            </div>
          </div>
        )}
      </div>
      <div className="flex-1 p-4 landscape:p-5 bg-white text-left">
        <h3 className="font-bold text-base landscape:text-lg mb-1">{name}</h3>
        {description && (
          <p className="text-xs landscape:text-sm text-gray-600 mb-2">{description}</p>
        )}
        <p className="text-blue-600 font-bold text-lg landscape:text-xl">{price.toLocaleString()}원</p>
      </div>
    </button>
  );
}
