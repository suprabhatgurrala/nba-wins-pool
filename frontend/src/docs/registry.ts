export type DocsRouteName =
  | 'pool-guide'
  | 'app-guide'
  | 'auction-guide'
  | 'auction-strategy'
  | 'simulation'

export type DocsArticle = {
  name: DocsRouteName
  path: string
  navigationTitle: string
  title: string
  description: string
  body: string
}

const sources = import.meta.glob('./*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const articleOrder = [
  './pools.md',
  './app.md',
  './auction.md',
  './auction-strategy.md',
  './simulation.md',
]

function parseArticle(source: string): DocsArticle {
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (!match) throw new Error('Docs article is missing front matter')
  const meta: Record<string, string> = {}
  for (const line of match[1].split(/\r?\n/)) {
    const idx = line.indexOf(':')
    if (idx > 0) meta[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
  }
  return {
    name: meta.name as DocsRouteName,
    path: meta.path,
    navigationTitle: meta.navigationTitle,
    title: meta.title,
    description: meta.description,
    body: match[2],
  }
}

export const docsArticles: DocsArticle[] = articleOrder.map((file) => parseArticle(sources[file]))

export function getDocsArticle(name: unknown): DocsArticle | undefined {
  return docsArticles.find((article) => article.name === name)
}
