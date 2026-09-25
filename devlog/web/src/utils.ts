import type { BugStatus } from "./types";

const SHORT_DATE: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
};

const DATE_TIME: Intl.DateTimeFormatOptions = {
  ...SHORT_DATE,
  hour: "2-digit",
  minute: "2-digit",
};

function parseDate(value: string): Date | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string): string {
  const date = parseDate(value);
  if (!date) {
    return value.slice(0, 10);
  }
  return new Intl.DateTimeFormat("zh-CN", SHORT_DATE).format(date);
}

export function formatDateTime(value: string): string {
  const date = parseDate(value);
  if (!date) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", DATE_TIME).format(date);
}

export function formatRange(start: string, end: string): string {
  if (formatDate(start) === formatDate(end)) {
    return formatDate(start);
  }
  return `${formatDate(start)} ~ ${formatDate(end)}`;
}

/** 只取 "14:03" 这种时刻，用于当天小结里按时间排开的提交。 */
export function formatClockTime(value: string): string {
  const date = parseDate(value);
  if (!date) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

/** 把分钟数说成人话：95 → "1 小时 35 分"。

    只用于"当天跨了多久"，不要拿它当工时：中间开会、吃饭都算在里面。 */
export function formatSpan(minutes: number): string {
  if (minutes < 60) {
    return `${minutes} 分钟`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} 小时` : `${hours} 小时 ${rest} 分`;
}

/** Bug 状态的中文说法。

    放在这里是因为 Bug 页和当天小结都要用：同一个状态在两处写成两个词，
    用户会以为是两回事。时间线卡片用的是另一套（"Bug 待排查"），那是
    为了在事件流里一眼认出这是 Bug，属于语境差异，不是重复实现。 */
export const BUG_STATUS_LABELS: Record<BugStatus, string> = {
  open: "刚捕获",
  root_cause_found: "已定位根因",
  resolved: "已解决",
};

/** 从绝对路径里取最后一段文件夹名：D:\work\demo → demo。

    末尾可能带分隔符（D:\work\demo\），所以要先去掉再取。
    取不到时返回空串，由调用方决定要不要用这个名字。 */
export function folderName(path: string): string {
  const parts = path.split(/[\\/]+/).filter((part) => part !== "");
  return parts.length > 0 ? parts[parts.length - 1] : "";
}
