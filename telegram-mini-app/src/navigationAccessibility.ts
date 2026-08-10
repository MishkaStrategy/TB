type NavigationCopy = {
  profileTrigger: string;
  profileDialog: string;
  closeProfile: string;
  primaryNavigation: string;
};

const COPY: Record<"ru" | "en", NavigationCopy> = {
  ru: {
    profileTrigger: "Профиль и настройки",
    profileDialog: "Профиль и дополнительные настройки",
    closeProfile: "Закрыть меню профиля",
    primaryNavigation: "Основная навигация",
  },
  en: {
    profileTrigger: "Profile and settings",
    profileDialog: "Profile and additional settings",
    closeProfile: "Close profile menu",
    primaryNavigation: "Primary navigation",
  },
};

const PROFILE_DIALOG_ID = "tb-profile-menu-dialog";
const CLOSE_BUTTON_CLASS = "profile-sheet-close";

function setAttributeIfChanged(element: Element, name: string, value: string): void {
  if (element.getAttribute(name) !== value) element.setAttribute(name, value);
}

function removeAttributeIfPresent(element: Element, name: string): void {
  if (element.hasAttribute(name)) element.removeAttribute(name);
}

function currentLanguage(): "ru" | "en" {
  return document.documentElement.dataset.language === "en" ? "en" : "ru";
}

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(
    'button:not([disabled]):not([tabindex="-1"]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
}

export function startNavigationAccessibility(): () => void {
  let menuOpen = false;
  let previousOverflow = "";
  let scheduled = false;

  const apply = () => {
    scheduled = false;
    if (!document.body) return;

    const copy = COPY[currentLanguage()];
    const trigger = document.querySelector<HTMLButtonElement>(".profile-trigger");
    const backdrop = document.querySelector<HTMLButtonElement>(".profile-backdrop");
    const sheet = document.querySelector<HTMLElement>(".profile-sheet");
    const nav = document.querySelector<HTMLElement>(".bottom-nav");

    if (trigger) {
      setAttributeIfChanged(trigger, "aria-label", copy.profileTrigger);
      setAttributeIfChanged(trigger, "aria-haspopup", "dialog");
      setAttributeIfChanged(trigger, "aria-controls", PROFILE_DIALOG_ID);
    }

    if (nav) {
      setAttributeIfChanged(nav, "aria-label", copy.primaryNavigation);
      nav.querySelectorAll<HTMLButtonElement>("button").forEach((button) => {
        if (button.classList.contains("active")) {
          setAttributeIfChanged(button, "aria-current", "page");
        } else {
          removeAttributeIfPresent(button, "aria-current");
        }
      });
    }

    if (backdrop) {
      if (backdrop.tabIndex !== -1) backdrop.tabIndex = -1;
      setAttributeIfChanged(backdrop, "aria-hidden", "true");
      removeAttributeIfPresent(backdrop, "aria-label");
    }

    if (sheet) {
      if (sheet.id !== PROFILE_DIALOG_ID) sheet.id = PROFILE_DIALOG_ID;
      setAttributeIfChanged(sheet, "aria-label", copy.profileDialog);

      const header = sheet.querySelector<HTMLElement>(".profile-sheet-header");
      if (header) {
        let close = header.querySelector<HTMLButtonElement>(`.${CLOSE_BUTTON_CLASS}`);
        if (!close) {
          close = document.createElement("button");
          close.type = "button";
          close.className = CLOSE_BUTTON_CLASS;
          close.textContent = "×";
          close.addEventListener("click", () => {
            document.querySelector<HTMLButtonElement>(".profile-backdrop")?.click();
            window.setTimeout(() => document.querySelector<HTMLButtonElement>(".profile-trigger")?.focus(), 0);
          });
          header.append(close);
        }
        setAttributeIfChanged(close, "aria-label", copy.closeProfile);
      }
    }

    if (sheet && !menuOpen) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      menuOpen = true;
      window.setTimeout(() => {
        const currentSheet = document.querySelector<HTMLElement>(".profile-sheet");
        const currentTrigger = document.querySelector<HTMLButtonElement>(".profile-trigger");
        if (!currentSheet || document.activeElement !== currentTrigger) return;
        focusableElements(currentSheet)[0]?.focus();
      }, 0);
    } else if (!sheet && menuOpen) {
      document.body.style.overflow = previousOverflow;
      menuOpen = false;
    }
  };

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(apply);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    const sheet = document.querySelector<HTMLElement>(".profile-sheet");
    if (!sheet) return;

    if (event.key === "Escape") {
      event.preventDefault();
      document.querySelector<HTMLButtonElement>(".profile-backdrop")?.click();
      window.setTimeout(() => document.querySelector<HTMLButtonElement>(".profile-trigger")?.focus(), 0);
      return;
    }

    if (event.key !== "Tab") return;
    const focusable = focusableElements(sheet);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["class", "data-language"],
  });
  document.addEventListener("keydown", onKeyDown, true);
  schedule();

  return () => {
    observer.disconnect();
    document.removeEventListener("keydown", onKeyDown, true);
    if (menuOpen && document.body) document.body.style.overflow = previousOverflow;
  };
}
