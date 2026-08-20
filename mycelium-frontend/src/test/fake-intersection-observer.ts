// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An IntersectionObserver stand-in for component tests. jsdom has none, and it
// is what tells the feed the reader has scrolled to the top; tests grab the
// latest instance and `trigger()` it to play that moment.
export class FakeIntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];

  private targets: Element[] = [];

  constructor(
    private callback: (entries: { isIntersecting: boolean; target: Element }[]) => void,
    readonly options?: { root?: Element | Document | null; rootMargin?: string },
  ) {
    FakeIntersectionObserver.instances.push(this);
  }

  static reset(): void {
    FakeIntersectionObserver.instances = [];
  }

  static latest(): FakeIntersectionObserver {
    const observer = FakeIntersectionObserver.instances.at(-1);
    if (!observer) throw new Error("no IntersectionObserver was constructed");
    return observer;
  }

  observe(target: Element): void {
    this.targets.push(target);
  }

  unobserve(target: Element): void {
    this.targets = this.targets.filter((t) => t !== target);
  }

  disconnect(): void {
    this.targets = [];
  }

  /** Play "the observed element scrolled into view". */
  trigger(): void {
    this.callback(this.targets.map((target) => ({ isIntersecting: true, target })));
  }
}
