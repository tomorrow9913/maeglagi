const capabilities = [
  ["Ask Workspace", "질문의 의도와 근거를 함께 확인합니다."],
  ["Context Timeline", "결정이 만들어진 과정을 시간순으로 봅니다."],
  ["Knowledge Graph", "사람·프로젝트·업무의 연결을 탐색합니다."],
];

export default function HomePage() {
  return (
    <main>
      <section className="hero">
        <p className="eyebrow">ORGANIZATIONAL CONTEXT PLATFORM</p>
        <h1>흩어진 업무의 맥락을 잇다.</h1>
        <p className="lead">
          회의와 문서에서 결정, 이슈, 할 일을 연결하고 왜 그런 결정이 나왔는지 근거와 함께 답합니다.
        </p>
      </section>
      <section className="cards" aria-label="핵심 기능">
        {capabilities.map(([title, description]) => (
          <article key={title}>
            <span>맥락이</span>
            <h2>{title}</h2>
            <p>{description}</p>
          </article>
        ))}
      </section>
    </main>
  );
}

