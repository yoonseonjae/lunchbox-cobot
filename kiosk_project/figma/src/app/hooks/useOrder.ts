import { useState, useCallback } from "react";

export interface MenuItem {
  id: string;
  name: string;
  price: number;
  image: string;
  description: string;
  category: "main" | "side";
  allergens: string[];
  isHalal: boolean;
  isVegan: boolean;
  isAvailable?: boolean;
}

export interface OrderItem {
  id: string;
  name: string;
  price: number;
  quantity: number;
}

export const allergyList = [
  "계란",
  "우유",
  "메밀",
  "땅콩",
  "대두",
  "밀",
  "고등어",
  "게",
  "새우",
  "돼지고기",
  "복숭아",
  "토마토",
  "아황산류",
  "호두",
  "닭고기",
  "소고기",
  "오징어",
  "조개",
];

export const useOrder = (allMenuItems: MenuItem[]) => {
  const [allergies, setAllergies] = useState<Set<string>>(new Set());
  const [isHalal, setIsHalal] = useState(false);
  const [isVegan, setIsVegan] = useState(false);
  const [selectedMain, setSelectedMain] = useState<string | null>(null);
  const [selectedSides, setSelectedSides] = useState<Set<string>>(new Set());
  const [orderItems, setOrderItems] = useState<OrderItem[]>([]);

  // 현재 필터링된 메뉴 항목 계산
  const getFilteredMenuItems = useCallback(
    (category: "main" | "side" | "preference" | "ad" | "pickup") => {
      if (category === "preference" || category === "ad" || category === "pickup") {
        return [];
      }

      return allMenuItems.filter((item) => {
        // 카테고리 필터
        if (item.category !== category) return false;

        // 알레르기 필터
        const hasAllergen = item.allergens.some((allergen) =>
          allergies.has(allergen),
        );
        if (hasAllergen) return false;

        // 할랄 필터
        if (isHalal && !item.isHalal) return false;

        // 비건 필터
        if (isVegan && !item.isVegan) return false;

        return true;
      });
    },
    [allergies, isHalal, isVegan, allMenuItems],
  );

  // 알레르기 토글
  const handleAllergyToggle = useCallback((allergy: string) => {
    setAllergies((prev) => {
      const newAllergies = new Set(prev);
      if (newAllergies.has(allergy)) {
        newAllergies.delete(allergy);
      } else {
        newAllergies.add(allergy);
      }
      return newAllergies;
    });
  }, []);

  // 메인 메뉴 선택
  const handleMainSelect = useCallback((id: string) => {
    if (selectedMain === id) {
      setSelectedMain(null);
      setOrderItems(prev => prev.filter(i => i.id !== id));
      return;
    }

    const item = allMenuItems.find(m => m.id === id);
    if (item && item.isAvailable !== false) {
      setSelectedMain(id);
      setOrderItems(prev => [
        // 장바구니에서 기존 '메인'만 지우고 '사이드'는 남겨둡니다.
        ...prev.filter(i => {
            const mInfo = allMenuItems.find(m => m.id === i.id);
            return mInfo?.category !== "main";
        }),
        { id: item.id, name: item.name, price: item.price, quantity: 1 }
      ]);
    }
  }, [allMenuItems, selectedMain]);

  // 사이드 토글
  const handleSideToggle = useCallback(
    (id: string) => {
      const item = allMenuItems.find((m) => m.id === id);
      if (item && item.isAvailable === false) return;

      setSelectedSides((prev) => {
        const newSides = new Set(prev);

        if (newSides.has(id)) {
          // 1. 이미 있으면 제거
          newSides.delete(id);
          setOrderItems((prevItems) => prevItems.filter((i) => i.id !== id));
        } else {
          // 2. 없으면 추가 (최대 3개 제한)
          if (newSides.size >= 3) {
            alert("사이드 메뉴는 최대 3개까지만 선택 가능합니다.");
            return prev;
          }
          newSides.add(id);
          if (item) {
            setOrderItems((prevItems) => [
              ...prevItems, // 기존에 담긴 메인 메뉴나 다른 사이드 메뉴를 유지!
              {
                id: item.id,
                name: item.name,
                price: item.price,
                quantity: 1,
              },
            ]);
          }
        }
        return newSides;
      });
    },
    [allMenuItems],
  );

  // 항목 제거
  const handleRemoveItem = useCallback((id: string) => {
    const item = allMenuItems.find((m) => m.id === id);
    if (!item) return;

    if (item.category === "main") {
      setSelectedMain(null);
      setOrderItems((prev) => prev.filter((i) => i.id !== id));
    } else if (item.category === "side") {
      setSelectedSides((prev) => {
        const newSides = new Set(prev);
        newSides.delete(id);
        return newSides;
      });
      setOrderItems((prev) => prev.filter((i) => i.id !== id));
    }
  }, [allMenuItems]);

  // 상태 초기화
  const resetOrder = useCallback(() => {
    setAllergies(new Set());
    setIsHalal(false);
    setIsVegan(false);
    setSelectedMain(null);
    setSelectedSides(new Set());
    setOrderItems([]);
  }, []);

  return {
    allergies,
    isHalal,
    isVegan,
    selectedMain,
    selectedSides,
    orderItems,
    setAllergies,
    setIsHalal,
    setIsVegan,
    setSelectedMain,
    setSelectedSides,
    setOrderItems,
    getFilteredMenuItems,
    handleAllergyToggle,
    handleMainSelect,
    handleSideToggle,
    handleRemoveItem,
    resetOrder,
  };
};
