import pandas as pd
df = pd.DataFrame({'A': [1, 2]})
styled = df.style
html = styled.to_html()
print(html)

