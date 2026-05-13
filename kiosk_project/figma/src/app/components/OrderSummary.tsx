import { ShoppingBag, Trash2 } from 'lucide-react';

interface OrderItem {
  id: string;
  name: string;
  price: number;
  quantity: number;
}

interface OrderSummaryProps {
  items: OrderItem[];
  onRemove: (id: string) => void;
  onCheckout: () => void;
}

export function OrderSummary({ items, onRemove, onCheckout }: OrderSummaryProps) {
  const total = items.reduce((sum, item) => sum + item.price * item.quantity, 0);

  return (
    <div className="landscape:flex landscape:flex-col landscape:flex-1">
      <div className="flex items-center gap-2 landscape:gap-3 mb-3 landscape:mb-4">
        <div className="bg-blue-500 rounded-full p-1.5 landscape:p-2">
          <ShoppingBag className="w-4 h-4 landscape:w-5 landscape:h-5 text-white" />
        </div>
        <h2 className="text-base landscape:text-lg font-bold">주문 내역</h2>
      </div>

      <div className="max-h-32 landscape:flex-1 landscape:max-h-none overflow-auto mb-3 landscape:mb-4">
        {items.length === 0 ? (
          <div className="text-center py-4 landscape:py-8 text-gray-400">
            <p className="text-sm landscape:text-base">선택한 메뉴가 없습니다</p>
          </div>
        ) : (
          <div className="space-y-2 landscape:space-y-3">
            {items.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between p-2 landscape:p-3 bg-gray-50 rounded-lg"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-sm landscape:text-base truncate">{item.name}</p>
                  <p className="text-xs landscape:text-sm text-gray-600">
                    {item.price.toLocaleString()}원
                  </p>
                </div>
                <button
                  onClick={() => onRemove(item.id)}
                  className="p-1.5 landscape:p-2 active:bg-red-100 rounded-lg transition-colors ml-2"
                >
                  <Trash2 className="w-4 h-4 landscape:w-5 landscape:h-5 text-red-500" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="pt-3 landscape:pt-4 border-t-2 border-gray-200">
        <div className="flex justify-between items-center mb-3 landscape:mb-4">
          <span className="text-sm landscape:text-base font-semibold">총 금액</span>
          <span className="text-xl landscape:text-2xl font-bold text-blue-600">
            {total.toLocaleString()}원
          </span>
        </div>
        <button
          onClick={onCheckout}
          disabled={items.length === 0}
          className="w-full bg-blue-500 text-white rounded-xl py-3 landscape:py-4 text-base landscape:text-lg font-bold active:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          주문하기
        </button>
      </div>
    </div>
  );
}
