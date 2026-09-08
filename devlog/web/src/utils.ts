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
