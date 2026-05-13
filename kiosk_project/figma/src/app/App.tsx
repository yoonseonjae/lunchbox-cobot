import { useState, useEffect } from "react";
import { UtensilsCrossed } from "lucide-react";
import { OrderSummary } from "./components/OrderSummary";
import { useOrder, type MenuItem } from "./hooks/useOrder";
import {
  submitOrder,
  watchOrderStatus,
  watchRobotStatus,
  db,
  rtdb,
} from "./lib/firebase";
import { StepAd } from "./components/ui/StepAd";
import { StepPreference } from "./components/ui/StepPreference";
import { StepMenuSelection } from "./components/ui/StepMenuSelection";
import { StepPickup } from "./components/ui/StepPickup";
import { StepConfirmation } from "./components/ui/StepConfirmation";
const menuItems: MenuItem[] = [
  {
    id: "jeyuk",
    name: "제육",
    price: 8500,
    image:
      "https://images.unsplash.com/photo-1777598405371-e657109ddd50?w=400",
    description: "매콤한 제육볶음",
    category: "main",
    allergens: ["돼지고기", "대두"],
    isHalal: false,
    isVegan: false,
    isAvailable: false,
  },
  {
    id: "tonkatsu",
    name: "돈까스",
    price: 8000,
    image:
      "data:image/jpeg;base64,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",
    description: "바삭한 돈까스",
    category: "main",
    allergens: ["돼지고기", "계란", "밀"],
    isHalal: false,
    isVegan: false,
  },

  // 사이드
  {
    id: "kimchi",
    name: "김치",
    price: 1000,
    image:
      "https://th.bing.com/th/id/OIP.VT61Xpqmni45qCaBbXubrAHaE8?w=277&h=184&c=7&r=0&o=7&pid=1.7&rm=3",
    description: "갓담근 배추김치",
    category: "side",
    allergens: ["새우"],
    isHalal: false,
    isVegan: false,
  },
  {
    id: "danmuji",
    name: "단무지",
    price: 1000,
    image:
      "https://lottemartzetta.com/images-v3/932dcbc7-fca8-4d43-bcde-f73d1ce3cc7d/584fdf3e-a202-4197-bdea-15a7812a67fa/500x500.jpg",
    description: "노란 단무지",
    category: "side",
    allergens: [],
    isHalal: true,
    isVegan: true,
  },
  {
    id: "pickles",
    name: "피클",
    price: 1000,
    image:
      "data:image/jpeg;base64,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",
    description: "새콤한 피클",
    category: "side",
    allergens: [],
    isHalal: true,
    isVegan: true,
  },
  {
    id: "salad",
    name: "샐러드",
    price: 1500,
    image:
      "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxETEhUSEBIVFhUVFhgYFhUVFRUVFRcWFhUWFhUVGBcYHSggGBolHRUVIjEhJyktLi8uGB8zODMtNygtLisBCgoKDg0OGRAQGy0mICUtLS0tLS0rLS0tMS0tLystLzAvLSstLS0tLS0tLS8tLSsrLS0tLS0tLS0tLS0tLS0tLf/AABEIALcBEwMBIgACEQEDEQH/xAAbAAAABwEAAAAAAAAAAAAAAAAAAQIDBAUGB//EADwQAAIBAgQEBAMHAgYCAwEAAAECEQADBBIhMQUGQVETImFxMoGRBxQjQlKhscHwM2Jy0eHxFkMkNIIV/8QAGQEAAwEBAQAAAAAAAAAAAAAAAAEDAgQF/8QAKxEAAgIBAwIFBAIDAAAAAAAAAAECAxEEEiExQRMiUXGBFDJhkQWxFdHh/9oADAMBAAIRAxEAPwDqS0taQtLFaAcWnJptaVNAhc0S0RNBKAHZoUmjpgHR0mjFACqFFR0AHR0mjoAFEaOkmgQuhRUc0AChNEaKgBU0KTQoAVNETQFJNAwTSSaFEaAFKaM0laOgAqS1KNJNABUk0c0kmkMbamyKcekUAMkUVLoUAKBpwU0KcFZQDgo6StGKYBk0tKbNOCmAqaOaTNCgBdGKQKDuB8RAoELmjmq+7xeyPzT7U1//AGV6Cs716jwy2mjBqgv8fy9qhLzM7GEWfXWPrRvQsmsmm2cCs9b43cLKCygHc9qmpduF80gqBPv7VnxU3hGdyLaaMGq/iGKuhM9pQe43Mdx3qofm1VRmdRp2NZs1NdbxJ4Hk1FFWZ4TzMlyXLSDt2qxTmCwfzR704XQkspgnktaFQ7fE7J2cVJt3QRIO9VUk+gxykmjmiNMBNEaOiNAAWjmiWhSAOkmiJoUDCNJozSaAENSaU1EKQDZFCjIoUAIU0sGmlNLWsjHgaUKaJpQankQoHWnKYtmnQaYEe9xG0jZWYA+tPfe7cSWEe9YbnvECzcV3PlP9xWG4jzWzELb06D515n1tqscdnCYm8HWOI8yKJFr61nMVxJ3MsxqmwRciTrt/FKFwkgDcmBTdzsWS9W3GSyTEVYYHEKxAYwO4osDgraxmUsT37+1Xt7C2EgXLSidtBBp0zym12LTpfCBhr2Hs/CuYnctqfqajcwcKOIt5sLc8N58ygAgjr7H1qSt7DrKqp2zTvoKYx/EPBXxLVssDEkD6HTpXTnKeXx+Ditio8NGfxPCrthQuU+WJYmRJO5PSp3EeJ3cP4bAq4kK4tnMBO2lWt/jXiIykBTl7TuNJHWsXxDigtDzMGaNABAEaAxXn2Thp29jy5dieMG8wfFkAJB7Sh3HtUDmDl4YxWZWVCViY0nuYrK8LxOa2cr+dzOb1j+K13L2GZLIW7cZnYauDIE7R6VbT6hahbZLp1G+Tm1g4jBXjhLyh1LCCs9dmU9v+a1R4a8HKCT0kwKi8WFz763j5SMOmYMo3WMyz61Unmom3KnZpY9QK5bnJTxHoZjwa3CWSkloJA26/L6Uq0l4/iG54fUqCZqjuXcXewzthbb+IzIEkCSkhmfXpEio/EWx6KQ1i78OpCMdeu01OHixSeB5Na3FSq6uW7UvhnN1r4LnfeuYYHil1WyyYG4aZ9tdqvcLiLZPmQAEanr9aVdltNjnJ5KQw+rOqYXG27glHBp9q5/gsRh1IXxYJ1UzBrTYPHXVWT+KndfiA9q9anWRnwy06XHnsXC0dNYTEI4lDPp1FOk12J5JBGio6KgBJpNKNJoAQTQo2oqQCKOio6AI604lMg04DWDQ5NAnSkTQuGmA5aNHfvBVLHpRW6o+YsXpkB96G8LJlnP8A7TbfjWRiLRJ8FytxZJgNEN8iR8m9KyXKnEguZbi5l0iY0arg8cXD4x7d7zYe+Ml1TsAZAb5SQfQnsKhHle/axPgWrb3rZbOpQEk2tNZ7iYPtXn7U06335RiSNnhQSohsp3HvTWOxd9XtZJCllJyaAHdpLADvVpcsXMNh08dMhmACUYxuAYO4FZvmItcRGtXJzEKYAGVRv/3UHDbjPDRlF7e41dwzC7iPMplRl+OdCuaTBkSdNKu+LYu3dFjJeRWZTCu6qSNDInaudX7L4u5bRNRO/wDlGjGtphuSuHlV8e25YRqrsJA6GD19IroozKLT6MrXOVct0SxtILOrkFp7yAp0PvpSBbINzwsQVRtVtaAMY1C6SPYVWcCsG+r2LjXJRioYLqLYMIWcyAY+fvUjiyYHC21W7eJKmVZyDlO3SJ9q5YTsjJvtngtG7fPMxi9xlFQZ2kxrp1G0xtXPOIY1rlzKubMzagazOigDvWrsrYvWv/jt4rlmBykAqF0DMp1ymRrWctWraO7XVaVOWJiGk7MNAfKaKtNsbm+Wzkm+Td8r8Db7sxdclyfIGlSQBrI6a6U5gOar3ieHesXLfmy5ssoRsDnGg2rOrzOXjNOgVQFjLlgas27Ppr0q1wnEtdNRTtvhT9i936no6X+PnZDcbSzw2211rpQEXAoM6gwIFVv/AInhbV/x7drqJtrtPcAmKRa42yrmAzRGg0EDuBSDzXOmWGOx0In+f761erVaexej9u5x30zpltkX2Jyo5ZIAyaqdOuoEbHaqe7jHuicHicrDe1cEn99arMeb2Js3rdqVvMZABH6tp7HL+9WvC8BayWzctZbqAZg/xq0QZPUeu1QuvSTkk+pmMXIkWsJcuIPvaWrh6ykEe28VT8W5YtH/AOtcCk7I5OVj+kMdQfeasuN8fSwuZj1APpJiYrI803cUwQ3LitanPbuJ5VOmmo2Inauau2c15ller6jlBJ47jV7Buzfd2tkXF22DAx36j+a1fAcHcs2hmunPGvYenrUHhOPTE2AxYNew4ANwiCVYxBpy9i2HXbtUr57GlE3G2ajtzwJv8Saw/lJ7k+5rXcH4wl9egft3rjnG+YMl8BtVbysPQ07wfj72b4tMdDrbfup2B/ivR0V04xW4vsU61LuduojUPhHERft5h8Q+If1qWa9dPKyjmCohQoCgBLUVA0mgAUKKjpDIYpwGmVNLmpmhxTQY60lKA3rQDly5lUnsK5Z9oPEnQ22Ukecz6+ldG4xdi371z7i+Kw15kVrZYhwJJ8oPt1qdssGVJJlbwrlhMZcXEXZyaGP1f8VubnGBYizaGUxC66QBopqCMdkSAIy7CI26xVPdui4+eZPX09K4ZWSy0uH2K+GmslFx3i1+5ccXCxYHVT+UdI9PWozFkt/imJ1y/mg/xPetJxmchu2UDNbGukmOpA6xvWBbx74uXEDPkEsdzuBAA3327VOMJS6nM1h8m1+zy4Hu3b7kBEHhoo7nUgewA+tbm1ezPMyPSuPcBxLoASXEnS2CRJPeNR/Nb/lviz51Fy1kSTLOrADt5CJJNX8XbiKRuCb6IvcddAeDdS3bAlyXCswHYDYetQeI8kYTHYbOjqbrCUvgsVnoD3TpFJxfJuBvMXtj7vcL5iyM7q0mWDWyQsHUaRH7VcXRZwFjMGIQCAArsHueY7wQs+9arrUZObaZvY1x3OW3OTOLcNurfs5WCk/iWWDgCJOZGAaI9D0rO8XxD37huXmJLEkxAGu/lGldWwXOFy6AL2DvFn28K0zZl6AgiTv7VmcTwzCWC1/FYXF5LjkYfDuvhZ/hku+6LLQF0Pv0pJ55RmxSjLzFXyXghFwKjXSIOQDWCYnfeurcE4PgigDZmzAdYyHqPLvrXO35nGa4qAWMLbP+FZCKGYQMjONXJ1PUdNd6ncH5nbMmFwNh3ac0GdEYgyYnLGaCx0Fc+FKWZRz8FKbLOkXj5wazifDctwrbUqkab6gfEfUajWqnEYQDWBM7/wBnb5Vt7eVAHc5rkRO4AMSgP6dB7xWY4yLVsttkaWA6qTuoPRfT19K5NRo9mZwePwdPifUNQkufXv8A9FcN4zaW2tpUPii4MxnoJAI9PSmbvGLty6Ue3dRkBAbKchBIEhjoZ0iswMV586kDUaZoYAbe5rQ2/EulChUQfxAzFZABgroRmmBrAial4tknt9ePQxbpUoJ18+pn+eQTaW47jKHjKvxFoO8+xp/kjCXcRg7+HcP4bmbdyPKrqdlPXUCQPWrI8PTMCVN0Zw3hvlPnBEFco116VvMNaZLRyYdUYyy2syqCx1JjZZPt1r0tMozj7HLKM4PElyYrg3DrthXVrYR8yDI7JmKqcxYgEjbpUXnLGLbvONBIUj2Kj/mhzbw68rLcxBNrxCRKOHIzQWU6adKoeKcNbEqgt3PFuWPw3I3ZDJtydpGo+dctta5jLhJ/7MLGMmC47iS7k1Ka8Xw9tz8Vpws/5W2/cCra7y2tuw2JxR8MElbNsEF7j7TO2XrI6VWWzOHuRt4iKOxI1P8ANdnCjHHZnRR3j+P6Oq8p8VNtkadDAb510do3Gx1HzrjXL7ygFdW4Ffz4dCd10NdFDfMRWrnJNNEKM0kV0EgGkUo0k0hhUdFNCgCCFozQJogambFiaNKQTS1OlMRn+feJeBYzRMAaehOtYbhV61dD3WnKCAABuSJ17RWl+1ZJtGdsg+cGYrI8v4HxUAsjKh6mQCYP12ia4NVPbJyfb9HPIPE8QfW49yY8oG37daLDcTUEa77jtWqwOBt2beVlUvHnaJJPz6VA4o2HVfxVTKdoAB/bWvP+rUnjBWFriHgcXDadajY1VsFXsKED3DmKkiHaANNsp29CR3qpwl9VchWLL6iI/wB6tsSc6HSQdD2rpzuWC0oqSyQ+KY24uIw11lVVzwGhM5cg+VjvlMdNNe8VYcZ4yWAYd/eKrceqYvDMh0vWAXUkxqokGexAg9jB7VDxd4OkL6biPfqRU020k+3DOvQY2yXdEy3x+4SMrEHuN6tm5oYPbXGov3UtLOomGHwK4/KhM6/Ksfh0ysJ19tqtOauGN4ti3ZutqPDumAAVcByIkhgAD9atBbJcPjuV1HNWcco6wvHVYAqwyZQRBmZ2gjpR+PZxFt7NyMrrGvfow7EaEeorlHGcPjJYWWC2QFCZSshQgIA+Wv8A1WTu3MXhgjriCM0wFuywAg+ZJ0HvXXXKfVnmOPlyN8d4Hdwl5rNwgw0K4DBH01IkTuYruHJ/KKYXMxv57hQIWVMoyAkgHUyZJ1ntXKeUvExGJtLed2TNmfXSNW8xHdoEnfNXbMPfUGC8BjJI39q2nl5aJdSv4xxizYfw7jgN0Hf1rnHH+YDduuFbyg5RE6+5rX8e4TgrjtcdSbmgZgzjMoMAQDAMQK55xq5ZGKW1aXKkiVnQE7rr02Nc9i3+xWu2Vb3IkYbCm2zXMQvkADBcw8xImNDIrS8P4lacqLbEychBEw+UsVMexg+lc/5g4vmYhGmNzuPYf71d/ZHiCcQ6nWPxFPZ9R/WofSuyOZFadS4Ny9TpgwVxEDlGUTIYgiD09qm8F5kF2VDQyEqymMynqPbsau1KXLRR1LA/HMjrMyDI1iuTc88uYzCOMRZeRoviJALDWAw2zCToemx0q9WndEsxflfU3bcro89V/R0bi+BuYi2PCFp2Vg+W8CVaARl9CZ6+lY69i/ugCphLaA/4rONfEPxIqjQa9e1U3I/OmKXEC3inZrb6MxCgoT8JkAaEkCPWui8wrZxFl7V5gAw0uwJUjVW9YirWwjZE4nB5yYDjGHTH2wCUt3EgZyGIVJmFUGBOlY/iWFazat2gpJzsxj1MA/QCp2H40bLsoYMASumzAEifY0vh3FBisQVu6KsZAo8oPtXBUrYyxL7VyUrk4pv14LjliY1Hyrp3KTfhOOzCsLgEtC4BbIOkEe22lbvltYS57r/SvRoacsoJSykW5NJU0VGK6RBmkGlGkNQAKFFQoAgE0BSGNHNSKCiadGxplTTqUxGP+1m0fBDj9IBrmvLvEr6KAhIRD07t0muyc32fEwRMAlQQQRI01Ej5VwlOJm0zG1KSfNbnMh+RqF1ak2sdeSGDWcc5kd0WCFadYmSKxuPxrO0lpJ/VOnzq9tLZvFYIV2IEQQAdpNQMbyxiHdhYQ3FXXMvwxPcx1B+lQorhB4wCjgVwXFMAEcaiYMgyBrEitFZxRC6N5DrHSelYs8JxWGuWmvWXQFlgnY6xEgmDvodat8FjvDdrTjQOwHtJitW1c5R0Vy7E3iNksrFSVkZcwMEZv36UrCWrj5baifhST5VB2XMx0E6708QD6irPG8OvDD/eLdprVklQMtwsSVPlduu+x01qbWUd2maUn+Sby7yrc+8m3i7QyIhY+eAwM5WRh8QBGuvvTfEmwC4a62FuG5c2s5jla0xDDNl0ziJ1jb61t+H4K1aUQH1AzeJde6QCBmUZiYBjUDc/KuYc4cJtYW9lsuSrAvlIgoCxyrpoRvHtV7K1GPCRiFrtk4ybMvg+OYq2uW3edQYBGh+HoJBy/Ko3jknM3mJ/VDH96F0DMR3/AJ60L+HZQCQRmEieokiR6SD9KomjisTTwy15OxxGJYEZlNtvKWKrIiC0bxJj1INbfAcWd3ItGRm0JidvMs7ECRvWS+zTg738Q9w6WkQq7erxCjudJ+ldUucEwxK+GiWVGrC2D5jprrttXBrLq1mLfOCWH2M5xLHM2ZVChgNCdsx2JjcVjrnBsdel2w7EoMsoqqCRJJ1jMdTqNzXYWS2ggW1I7nU1meNPdw6HwifCbWNwh7DtvvXNptZXDyFK6pTko+pyPCcJv35Fq2x82pbyqNwZLdR23rV8t8Kt4N0uYi44dbin8HVcoOqsTqViToNdqm2eM3EcXEIzAzqJGtN43HPeLPcMsxkmux6qT6I9aH8dBfc8nYcLi1I8vmRh5SD3G9YnmfibP5NRbB8yHqyyJOnqRWc4bxu/YtMlvVW0lsxyAqR5ddO/oaXDFVMzM7SSInf+ad97lFJfI9No1XNuXwRcfw1N1im7d90/9h9iZ/k1JxDhQpecnXLGYesHern7O8TYvI1t0Dech8yhg2xUwdtIqVNbs6srfaquiMXjGW6xBA16gAH61Ycg8NH3mCVKAnMX0BAnQmtR9oPJapZ8Xh6NmB86JLDJGpUEyCCBoO50rkRYsRnY+U6CPhM9u9dcaHFY7Hkam5XdFg6zjcGVxQYKF840Ggyttt01rovB0y2R/mefpXGuCcwYu/etozteJZUlkQHUgLBUDQV25FAYINrax8+tWoSWTlin0HjQoGiq5UJqQ9GxpNw0ACaKkTQoAgA0qabU0c1HJQcFOqaYmnQdK0ZCtoGz2W2urp/qH9isMn2a4DVrz3XcO0qrgKBm0UgLIMb69a2eMBy5l+JTI+W4qm5vxtxcM2KwygkwLoAJIbRVc/5e/bQ0OXBiS5yYbnu4lsK1i2qldso/KNIIFQuSsVibwuW1i0jAhXkHLcjNGU6spG8ajcVW47EuzEsd9+1MYPFtYcXrZhlJIkSNRB0rkTT6orGlvOeDfc62AbdsG4gcMmZNJYEj4eo7+1ZnjbW8QLeHwto+KGYsVTzFu87kdateVBhuJM17Eh1xFoZCbcBSsk23KkHUCV+XtV7wvhgwNq8blxGlyy3ACpywNGnbWdBpWud2RRawc44ZiHBNu4CGUlWB3BG9a65x+0uFXDraLH42JYqBcDSDpq3TsNIrC8axpfEPeSPMemxjr71O4Vf8QoGZVzGC7zlXfUwD2pT3LmJ16eMc+c6PgOZ7ZS0cQyK9wPPmkDJJLESSsgaA1g8c/wB4xLlHLeI8W80AtqAimYCiNp7CpvMHKl5BeuSptWssuxy5swWMq9fiH96U1yoAjqMTba2jMuW8wuKAUYMApjK0sFBnb+dYlJJMI7ISk4kR+Ub727rtburdtnyWvCfNc7wfqNJ2NSOK8k4y1hjdufiMoEJaObLbC5iGUgNprtXSuI8zNaxCYVMPednUFWVT4fqfUADUjal466FLKzhlYCQfyzoQI6H19athJYOOcnJ5ZzLkPj6W4tuQiGQx6ExKk9tomtvhuYLLKQjoyqYJLajtuKw/O2Bs2VFyzZFqWgBQqhvUge2lZY4ht16j0rztToIWy3Lgnlo61ieZbKtuTH5RlYH/APU6e1It8wpckMIEahysEbER/SuSHHuNyT8yD9aUeKuFgRrrPX/upf4tYFlmx4rcKM1hD5C/iZf0sQQBPWFNQzjEQGTr2XVtBJ03FUmH4q1xma4STAAgak9Bp0qLieGYmVL2ntozAZ2DZVkxLt0+ddlemfSTPQ+tlGCS6mgsccL/AIVmyxLwBr5iSdIAME1qL+GdS2bRlJDQAuvsug9qy+I5QxOHtDEC5bZRBBRyHALeVgOvTUHT5Vr8J+KgfMWJUBpmZAgHUzBA0PWp6mtRh5Smk1LnZtn8GNxqcQPi3rKk2UIzFAhZQYGoPmiZ2qx+z3jFtHfO+V31/KEOkZvRu/fSr+xxLwZW/aQXF0K5IR7cAhiwME+oHSlcC5J4bjMS7l2ykZ/AQwFJMNJiQvYadfl0wUeEjinfKTakbK1j5skkwYO2vTeuKPwG89x2RSULki4/lDSZ0n4jr0rqGJ5cxWGeLSm5ZkLbOeWXMSFziNvhE0nF/Zpeu3M2Iv2/C/NlzhwJEgAiCdxM034je1L5Odvngg/Zfy89p7mMvghbUpZU/nuEee57KDHuT2ro/DzoWO7GarHdWKWbQy20AVF7Afz71cqoAAHSrxWFg2o4Q8aKimimtjENvSXNGd6S9ABUKOhQMq5oxSBRq2tQKDtOCmFNOBq0ZYsmqo3vAuHSbbyGU6gg7girFm0pjFWA6EH5ehoeewL8nOudeXfu/wCPYl8K50O5tMfyP6dm+W++Cx93MQF+fp612rCY1rRZHUMjSrowBVgdCCDoRWR5j+ztWJxHDs1y2dbmFn8VBMt4RPxr6fEOmbpONcW8r9FbLpuO1/soeSbr4fE2XOiXw1uNdmjK5H+oLHpNXvM/GPFiy3mAILTtK7D1qqLr5EKxkAADDzDKBE9jpVfi3MyBGtcspObycangVw7l9sViPCtMFnVifypIDMF6xO3rWyxfK+Fs4O9aVWe5am54zQG12EjTLE6e/WKnfZ7y26A4i8oHiBTbOdsxQw3mQaAaKRJneRW+MKJ00G4FdcYeXDKwtksGY5Txt3EYZXuAN5iuimPI0AweugNXzs0FLgJDCCPQioPBHW1aORMim7dJHxa+KwJJ9Yn0BA6VYPiBEkgDuY0Fai+MZ5FN5baKjiGIxYLJYa1lgeGCGkKMocuRppOnyrlvH8ZjL0LdzW1Vj4ht50LQdSQYI0GgPatfxzH27WODi9mNu1KhWKgeK2uYA6n8Mb6bH2cfitjGnKLii9l82ZZzqsaiCNRpr2rnnet7g85X6NVzin5jK884606/d/GUzlggTlIAjP8ApHqNd6wONw7WnyZg0QQVJKkETpNdD5g4fcgYdWUIfMFyqqlgCNDG9Z7gfCrbYoLix+GglpIKDogdp0UnT3gdapC1MMRkvKzLIrt8IJgEmBsF1J9hWu5c5UXEYU3XJBZmVCdFDDyqfWW0+Vbi7juH2vwjctAEBRbTzGCAAMq9Ij5VnrnE1tqbHD0OQXCfMCF0jadTrr8q1KxJDhTKb4RkeI8Iu4a94JGZxEZZhgRII6xv9DXdLGGZkGdRqon9M/7Vg7GFe9irWJugTbUDKNMxUsVaTtBYGI6V03DYa94fiZl1Eso1yrHedTWIXRm3t5KS01kPu4KrD8tYLMxxarfLt5c+bLbBGULbBPlPWd5OlUWMv38Lf+63bpuWIASQNLZ0Q6DQrEe4pfO2Hu37ASwxW6rqyQ2WdCrCe0Max91L2Hum3dM6g54YBtAYltwDU7LlKHlIW1TrfJJ41xbFBhh3toVtsChyk5ljytB6EGSK1/2SYFy2IxJZAr5VCidCpYtIOgHmEb9aHB0w2JNlLyEskgCZD9pG8Ca2SWLOHBgKgOvhooWW2zGPYa71XT4mt0TLm5dS2bTzFhA3P971nuK8Uz+VNFH1Pqai8Q4m1zTZRso2pvA4fO3oN6tKfZG4w7sseEYeBnPXarSaaURAG1HNaSwgYtX6UlnomFEKYAWkudaWKbc0AKmhSCaFAFYDRKd6TNFOlRKD9s0oGmVNKmtCFsaLNpTTNSGuaUxEXieFzDMvxD9xVRh8UyGVJBFXV25VJxOJzDQ9anNc5RuLzwydjBhcWIxSQ/S8gAf0zTo3z19azXGORr4GfDkX0j/1/wCJ87ZM/QmpiXqmYbHMplSR7Vjyy6oxOlPoHyrzDikFu1i8Nd8KRbXElWUAwcq3A3qAubuQDqa2PErhFm4yTmCMRGp26DqaqMNzM8ZbgDqRBDdQdxU3DcTwxUJDINonMP31qyw1jJPY0OcRbJZkxIEn8o9dOmtc2+0rEYkW7V2w8WQCr5dSrMIBadCpB0PQn2rZ8w4G7iLJtYfE2RM6uHVo1IEiR1X6VU8N5RxfhFMQ9u5mkMqMjIVJ280SPl19BXParIz3pZXoUrjueM/s57ydw+3kZ7i+VgRIkN6Feja9PTcUnC4fwMStwk+UmOnQj+tdK/8AE7iiBaf5ZT7bVWYrk9mMvYvn2EfwK5ZWzk3mLXwztWiq2/cm/cu8Tyr41kFb8uSGBPwARqIBPyNSuG8vWLFhrd3I4afELDRpiZnpoPpVc9vGhQluxcVQAAApGgEComI4Zj7kC5buMJmG1AjbQmqxux9tbMLQpcua/ZF486taZL2HtgyAjrld8qt5DqAVBUAHpqRWWbHGzr4Ib0VoHy8ta48sYw/+sD/W6j+tM/8Ag95jN3EWUHUAlz+wFYcLbXzHg6651UxwplVy9zhYd1S5acMzZVAi4CTAG3m+gNdDvYHGW7RGXyasSrgkKdSpG8CqHlflHBYK747Xmv3BOWUVVQtuV6zGk+prWX+ZdIRB89a6VpK4xaTx7HF9ZY3ys+5nsPg7rn8NWb5ae87UOKcprdZTisSVRR/g24ZiZ3zbDTTrU3EcXuNpmgdhoP2qE1wnep1aaFfPU1qNRK5YaSRY4fEWrC5MJbCDbMdXPuxqJculjJM1HL0FM10OXZHPGCRJsoWIA61oMJaCrA+Z71XYABdt+pqbYeZ963BCkyYGo5pgNSw21UMjpNCaQWoppCFZqbc0dMu+tAxZehTZoUwKwnT3pTbimQ0sBTh3qCKDimlZqbFIZq0ZFO9MXX0oM1Rrz0wE3rlUXFL+sVY4i7vWb4hekmpzZuKIT8RKN3HarHCcRVxINZrGvrVZ4zKZUkGspZNNnRkvU+t6sTgeYelzT1G1X2Hx6sJBB9qMYAvVxBp1MYw6mqdMRTq3qeRYLpOJXBsx+tOji939bfWqMXqULtPcxbUXZ4vd/W31NNtxG4d2P1qrF2jF2nuYtqLA4pj1NJ8U96heLR+LRkMEvPQ8Soni0lr1LI8E3xKSbtVeI4gqiWMVUX+NliAmgPU7/SstmkjR38cq9de1LwWJLSTWWtNrMzNXuAfSfb+axk3tSRp8Pe0HzqZhLp81VOEuiB86m4a9JaOwq8WRki0DU6ra1FttT9s1UmOXGoI1MsZMULc0ASCaailgzSGNIBJNFSCaFMCss/EfTSnU3oUKijYqdaaY0KFaQiO7VGuNvRUKGMrMW9ZvEvqaFCovqUiUuJOpquuUKFaiDGHFLs3WXVSR7UKFbMFlh+OOPiE/sas8Nx9DpqD7UVClgMllbx4NPLi6FCsmhwYqj+9UKFAA+901c4iBuaFCgCBf5iQfDJP0/moF7jl1tBC/uaKhQAwGJMkkkzvrT2H/AC/OhQrLNossPuB2FXOCOgHtQoVM2y5wba/I/wA1MsYkZmA6L/WhQqsCLLC1dMVMt7UKFXRNgRtafoqFMyC01Ns2h96OhQAzmoUKFAz/2Q==",
    description: "신선한 샐러드",
    category: "side",
    allergens: [],
    isHalal: true,
    isVegan: true,
    isAvailable: false,
  },
];

export default function App() {
  const [step, setStep] = useState<
    "ad" | "preference" | "main" | "side" | "pickup"
  >("ad");

  // useOrder 훅 사용
  const {
    allergies,
    isHalal,
    isVegan,
    selectedMain,
    selectedSides,
    orderItems,
    setIsHalal,
    setIsVegan,
    handleAllergyToggle,
    handleMainSelect,
    handleSideToggle,
    handleRemoveItem,
    resetOrder,
    getFilteredMenuItems,
  } = useOrder(menuItems);

  // 주문 추적 상태
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [currentOrderId, setCurrentOrderId] = useState<string | null>(null);
  const [realStatus, setRealStatus] = useState<string>("주문 대기 중...");
  const [isError, setIsError] = useState(false);
  const [orderStage, setOrderStage] = useState(0);

  // 픽업 관련 상태
  const [pickupNumber, setPickupNumber] = useState(1);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [showPickupNumber, setShowPickupNumber] = useState(false);

  // 현재 필터링된 메뉴 항목
  const currentMenuItems = getFilteredMenuItems(step);

  // 단계 네비게이션
  const handleNext = () => {
    if (step === "preference") {
      const availableMainItems = menuItems.filter((item) => {
        if (item.category !== "main") return false;
        const hasAllergen = item.allergens.some((allergen) =>
          allergies.has(allergen),
        );
        if (hasAllergen) return false;
        if (isHalal && !item.isHalal) return false;
        if (isVegan && !item.isVegan) return false;
        return true;
      });

      if (availableMainItems.length === 0) {
        setStep("side");
      } else {
        setStep("main");
      }
    } else if (
      step === "main" &&
      (selectedMain || currentMenuItems.length === 0)
    ) {
      setStep("side");
    }
  };

  const handleBack = () => {
    if (step === "preference") {
      setStep("ad");
    } else if (step === "main") {
      setStep("preference");
    } else if (step === "side") {
      setStep("main");
    }
  };

  const handleCheckout = async () => {
    try {
      const orderId = await submitOrder(orderItems);
      setCurrentOrderId(orderId);
      setRealStatus("로봇이 주문을 확인하고 있습니다...");
      setIsError(false);
      setOrderStage(0);
      alert("주문이 로봇에게 전달되었습니다!");
      setShowConfirmation(true);
    } catch (error) {
      console.error("Order submission failed: ", error);
      alert("주문 전송 실패. 콘솔을 확인하세요.");
    }
  };

  const handlePickupSubmit = () => {
    if (phoneNumber.length >= 10) {
      setPickupNumber(Math.floor(Math.random() * 2) + 1);
      setShowPickupNumber(true);
    }
  };

  const handleBackToAd = () => {
    setStep("ad");
    setPhoneNumber("");
    setShowPickupNumber(false);
  };

  const handleReset = () => {
    setShowConfirmation(false);
    setStep("ad");
    resetOrder();
    setCurrentOrderId(null);
  };

  // Firebase 리스너 설정
  useEffect(() => {
    if (!showConfirmation || !currentOrderId) return;

    // Firestore 상태 감시
    const unsubscribeFirestore = watchOrderStatus(
      currentOrderId,
      (status) => {
        if (status === "completed") {
          setRealStatus("completed");
          setOrderStage(4);

          // 10초 뒤 초기 화면으로 복귀
          setTimeout(() => {
            handleReset();
          }, 10000);
        }
      },
      (error) => {
        setIsError(error);
      },
    );

    // RTDB 로봇 상태 감시
    const unsubscribeRTDB = watchRobotStatus((step, status) => {
      setOrderStage(step);
      setRealStatus(status);

      if (step === 4 && status === "completed") {
        // 10초 뒤 초기 화면으로 복귀
        setTimeout(() => {
          handleReset();
        }, 10000);
      }
    });

    return () => {
      unsubscribeFirestore();
      unsubscribeRTDB();
    };
  }, [showConfirmation, currentOrderId]);

  const getStepTitle = () => {
    if (step === "ad") return "";
    if (step === "pickup") return "픽업 주문";
    if (step === "preference")
      return "알레르기 및 식이 선호도를 선택하세요";
    if (step === "main") return "메인 반찬를 선택하세요";
    return "사이드를 선택하세요 (3개까지 선택 가능)";
  };

  const canProceed = () => {
    if (step === "preference") return true;
    if (step === "main")
      return (
        selectedMain !== null || currentMenuItems.length === 0
      );
    return true;
  };

  // 확인 화면 렌더링
  if (showConfirmation) {
    return (
      <StepConfirmation
        realStatus={realStatus}
        orderStage={orderStage}
        isError={isError}
        pickupNumber={pickupNumber}
        onReset={handleReset}
      />
    );
  }

  // 광고 페이지 렌더링
  if (step === "ad") {
    return <StepAd onStart={() => setStep("preference")} />;
  }

  // 픽업 페이지 렌더링
  if (step === "pickup") {
    return (
      <StepPickup
        phoneNumber={phoneNumber}
        onPhoneChange={setPhoneNumber}
        onSubmit={handlePickupSubmit}
        onCancel={handleBackToAd}
        showPickupNumber={showPickupNumber}
        pickupNumber={pickupNumber}
      />
    );
  }

  // 메인 주문 페이지 렌더링
  return (
    <div className="size-full bg-gradient-to-br from-orange-50 to-yellow-50 overflow-hidden">
      <div className="h-full flex flex-col">
        {/* 헤더 */}
        <header className="bg-white shadow-md px-4 landscape:px-6 py-3 landscape:py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 landscape:gap-3">
              <div className="bg-orange-500 rounded-full p-2 landscape:p-2.5">
                <UtensilsCrossed className="w-5 h-5 landscape:w-6 landscape:h-6 text-white" />
              </div>
              <div>
                <h1 className="text-base landscape:text-lg font-bold text-gray-800">
                  나만의 도련님 도시락
                </h1>
              </div>
            </div>

            {/* 진행 단계 */}
            <div className="flex gap-2 landscape:gap-3">
              {["preference", "main", "side"].map((s, idx) => (
                <div key={s} className="flex items-center gap-1">
                  <div
                    className={`w-7 h-7 landscape:w-8 landscape:h-8 rounded-full flex items-center justify-center text-xs landscape:text-sm font-bold ${
                      step === s
                        ? "bg-blue-500 text-white"
                        : s === "preference" && step !== "preference"
                          ? "bg-green-500 text-white"
                          : s === "main" && selectedMain
                            ? "bg-green-500 text-white"
                            : s === "side" && step === "side"
                              ? "bg-green-500 text-white"
                              : "bg-gray-200 text-gray-500"
                    }`}
                  >
                    {idx + 1}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </header>

        {/* 메인 컨텐츠 */}
        <div className="flex-1 overflow-auto landscape:overflow-hidden">
          <div className="h-full landscape:flex landscape:gap-4 px-4 landscape:px-6 py-4 landscape:p-4">
            {/* 메뉴 선택 영역 */}
            <div className="mb-4 landscape:mb-0 landscape:flex-1 landscape:flex landscape:flex-col landscape:overflow-hidden">
              {step === "preference" ? (
                <StepPreference
                  isHalal={isHalal}
                  isVegan={isVegan}
                  allergies={allergies}
                  onHalalToggle={() => setIsHalal(!isHalal)}
                  onVeganToggle={() => setIsVegan(!isVegan)}
                  onAllergyToggle={handleAllergyToggle}
                />
              ) : (
                <StepMenuSelection
                  title={getStepTitle()}
                  items={currentMenuItems}
                  selectedMain={selectedMain}
                  selectedSides={selectedSides}
                  step={step as "main" | "side"}
                  onSelect={(id) => {
                    if (step === "main") handleMainSelect(id);
                    else handleSideToggle(id);
                  }}
                  isEmpty={currentMenuItems.length === 0 && step === "main"}
                />
              )}
            </div>

            {/* 하단 주문 요약 및 네비게이션 */}
            <div className="landscape:w-80 landscape:flex landscape:flex-col landscape:h-full landscape:flex-shrink-0">
              <div className="bg-white border-t landscape:border-t-0 landscape:rounded-2xl landscape:shadow-lg border-gray-200 p-4 landscape:p-4 landscape:flex landscape:flex-col landscape:h-full landscape:overflow-hidden">
                <div className="landscape:flex-1 landscape:overflow-auto landscape:mb-4">
                  <OrderSummary
                    items={orderItems}
                    onRemove={handleRemoveItem}
                    onCheckout={handleCheckout}
                  />
                </div>

                {/* 네비게이션 버튼 */}
                <div className="flex gap-3 landscape:gap-3 mt-4 landscape:mt-0 landscape:flex-shrink-0">
                  {(step === "preference" || step === "main" || step === "side") && (
                    <button
                      onClick={handleBack}
                      className="flex-1 bg-gray-300 text-gray-700 rounded-xl py-3 landscape:py-3 text-base landscape:text-base font-bold active:bg-gray-400 transition-colors"
                    >
                      이전
                    </button>
                  )}
                  {(step === "preference" || step === "main") && (
                    <button
                      onClick={handleNext}
                      disabled={!canProceed()}
                      className="flex-1 bg-blue-500 text-white rounded-xl py-3 landscape:py-3 text-base landscape:text-base font-bold active:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                    >
                      다음
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}