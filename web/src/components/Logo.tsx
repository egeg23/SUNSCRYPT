export function Logo({ height = 28 }: { height?: number }) {
  return (
    <picture>
      <source srcSet="/brand/logo-dark.svg" media="(prefers-color-scheme: dark)" />
      <img src="/brand/logo-light.svg" alt="SUNSCRYPT" height={height} style={{ display: "block", height }} />
    </picture>
  );
}
