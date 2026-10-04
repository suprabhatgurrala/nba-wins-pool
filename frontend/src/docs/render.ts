import { Marked } from 'marked'

const imageUrls = Object.fromEntries(
  Object.entries(
    import.meta.glob('@/assets/docs/*.webp', { query: '?url', import: 'default', eager: true }),
  ).map(([file, url]) => [file.split('/').pop(), url as string]),
)

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

const marked = new Marked({
  renderer: {
    heading({ tokens, depth }) {
      const html = this.parser.parseInline(tokens)
      const match = html.match(/^(.*?)\s*\{#([\w-]+)\}\s*$/)
      const id = match ? ` id="${match[2]}"` : ''
      return `<h${depth}${id}>${match ? match[1] : html}</h${depth}>\n`
    },
    image({ href, title, text }) {
      const src = imageUrls[href] ?? href
      const caption = title ? `<figcaption>${escapeHtml(title)}</figcaption>` : ''
      return `<figure class="docs-figure"><img src="${src}" alt="${escapeHtml(text)}" loading="lazy" />${caption}</figure>`
    },
    paragraph({ tokens }) {
      const html = this.parser.parseInline(tokens)
      const onlyImages = tokens.every(
        (t) => t.type === 'image' || (t.type === 'text' && !t.raw.trim()) || t.type === 'br',
      )
      return onlyImages ? `<div class="docs-figures">${html}</div>\n` : `<p>${html}</p>\n`
    },
  },
})

export function renderDocs(markdown: string): string {
  return marked.parse(markdown, { async: false })
}
