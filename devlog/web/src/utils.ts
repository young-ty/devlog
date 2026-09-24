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

/** 从绝对路径里取最后一段文件夹名：D:\work\demo → demo。

    末尾可能带分隔符（D:\work\demo\），所以要先去掉再取。
    取不到时返回空串，由调用方决定要不要用这个名字。 */
export function folderName(path: string): string {
  const parts = path.split(/[\\/]+/).filter((part) => part !== "");
  return parts.length > 0 ? parts[parts.length - 1] : "";
}
