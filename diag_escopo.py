"""Mapeia o escopo das funcoes em historico-execucao.js.

O erro "abrirModalUnificacao is not defined" indica funcao declarada dentro de
um escopo e chamada de outro. Aqui listamos: nivel de indentacao da declaracao
(0 = escopo global/modulo; >0 = dentro de callback/IIFE) e onde cada uma e
chamada.
"""
import re
import pathlib

js = pathlib.Path('src/autoavaria/static/js/historico-execucao.js').read_text(encoding='utf-8')
linhas = js.splitlines()

print('=== declaracoes de funcao e seu nivel de indentacao ===')
for i, l in enumerate(linhas, 1):
    m = re.match(r'^(\s*)function\s+(\w+)', l)
    if m:
        nivel = len(m.group(1))
        escopo = 'GLOBAL' if nivel == 0 else ('dentro de bloco (nivel %d)' % nivel)
        print('  %4d  %-32s %s' % (i, m.group(2), escopo))

print()
print('=== onde cada uma e CHAMADA ===')
nomes = [re.match(r'^(\s*)function\s+(\w+)', l).group(2)
         for l in linhas if re.match(r'^(\s*)function\s+(\w+)', l)]
for nome in nomes:
    usos = [(i, l.strip()) for i, l in enumerate(linhas, 1)
            if re.search(r'\b%s\s*\(' % re.escape(nome), l)
            and not re.match(r'^\s*function\s+%s' % re.escape(nome), l)]
    if usos:
        print('  %s:' % nome)
        for i, l in usos:
            print('     %4d  %s' % (i, l[:95]))
