export interface Official {
  id: string
  fullName: string
  titleKk: string
  roleKk: string
  dayIndex: number // 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat 7=Sun
  dayNameKk: string
  timeKk: string
  topics: string
  initials: string
  accent: string
}

// Source: config/ai-agent.yaml (Nókis qalası hákimi + 5 orınbasar)
export const OFFICIALS: Official[] = [
  {
    id: 'hakim',
    fullName: 'Daniyarov Abatbay Saparbaevich',
    titleKk: 'Nókis qalası hákimi',
    roleKk: 'Shahár basqarıwı — baslıq',
    dayIndex: 5,
    dayNameKk: 'juma',
    timeKk: '10:00–12:00',
    topics: 'Barlıq ulıwma máseleler',
    initials: 'DA',
    accent: '#f7bd29',
  },
  {
    id: 'kannazarov',
    fullName: 'Kannazarov Muslim Azatovich',
    titleKk: 'Birinshi orınbasar',
    roleKk: 'Finans-ekonomika hám jarlılıqtı qısqartırıw',
    dayIndex: 3,
    dayNameKk: 'sárshembi',
    timeKk: '10:00–12:00',
    topics: 'Finans, ekonomika, jarlılıq, aqsha máseleleri',
    initials: 'KM',
    accent: '#40b0e0',
  },
  {
    id: 'erejepov',
    fullName: 'Erejepov Nurlıbek Maxsetovich',
    titleKk: 'Orınbasar',
    roleKk: 'Qurılıs, kommunal xojalıq, ekologiya',
    dayIndex: 4,
    dayNameKk: 'piyshembi',
    timeKk: '10:00–12:00',
    topics: 'Jol, suw, jarıq, kommunal, abadanlastırıw, ekologiya',
    initials: 'EN',
    accent: '#7ee3a8',
  },
  {
    id: 'otejanov',
    fullName: 'Otejanov Jeńisbay Jiyenbaevich',
    titleKk: 'Orınbasar',
    roleKk: 'Jaslar siyasatı, ruwxıy-aǵartıwshılıq',
    dayIndex: 1,
    dayNameKk: 'duyshembi',
    timeKk: '10:00–12:00',
    topics: 'Jaslar, jámiyetlik rawajlandırıw, ruwxıy isleri',
    initials: 'OJ',
    accent: '#c084fc',
  },
  {
    id: 'oybekov',
    fullName: 'Oybekov Odilbek Oybekovich',
    titleKk: 'Orınbasar',
    roleKk: 'Investitsiya, sanaat hám sawda',
    dayIndex: 2,
    dayNameKk: 'seyshembi',
    timeKk: '10:00–12:00',
    topics: 'Biznes, sawda, investitsiya, sanaat',
    initials: 'OO',
    accent: '#ff8e5e',
  },
  {
    id: 'dauletnazarova',
    fullName: 'Dauletnazarova Zulfiya Abatbergenovna',
    titleKk: 'Orınbasar',
    roleKk: 'Shańaraq hám hayal-qızlar bólimi',
    dayIndex: 4,
    dayNameKk: 'piyshembi',
    timeKk: '10:00–12:00',
    topics: 'Shańaraq, hayal-qızlar, balalar, shanaraq másleleri',
    initials: 'DZ',
    accent: '#f06aa5',
  },
]

/** Returns officials whose reception day matches the given weekday (1=Mon..7=Sun). */
export function receptionsForDay(dayIndex: number): Official[] {
  return OFFICIALS.filter((o) => o.dayIndex === dayIndex)
}

/** Today's weekday index, Monday = 1. */
export function todayIndex(): number {
  const jsDay = new Date().getDay() // Sun=0..Sat=6
  return jsDay === 0 ? 7 : jsDay
}
