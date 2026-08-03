"""Mora列のAlignment

正解Mora列と認識Mora列を編集距離で対応付け、どのMoraで崩れたかを特定する。
Overlayでの誤り位置表示と、Localization指標の算出根拠になる。
"""
from dataclasses import dataclass
from typing import List,Optional,Sequence

MATCH="match"
SUBSTITUTE="substitute"
DELETE="delete"
INSERT="insert"


@dataclass(frozen=True)
class AlignOp:
 op:str
 ref_index:Optional[int]
 hyp_index:Optional[int]


@dataclass(frozen=True)
class Alignment:
 distance:float
 ops:List[AlignOp]


def align(
 reference:Sequence[str],
 hypothesis:Sequence[str],
 substitution_cost:float=1.0,
 deletion_cost:float=1.0,
 insertion_cost:float=1.0,
)->Alignment:
 """正解Mora列と認識Mora列をAlignmentし、距離と操作列を返す"""
 n=len(reference)
 m=len(hypothesis)
 dp=[[0.0]*(m+1) for _ in range(n+1)]
 for i in range(1,n+1):
  dp[i][0]=dp[i-1][0]+deletion_cost
 for j in range(1,m+1):
  dp[0][j]=dp[0][j-1]+insertion_cost
 for i in range(1,n+1):
  for j in range(1,m+1):
   if reference[i-1]==hypothesis[j-1]:
    dp[i][j]=dp[i-1][j-1]
    continue
   dp[i][j]=min(
    dp[i-1][j-1]+substitution_cost,
    dp[i-1][j]+deletion_cost,
    dp[i][j-1]+insertion_cost,
   )
 ops:List[AlignOp]=[]
 i,j=n,m
 while i>0 or j>0:
  if i>0 and j>0 and reference[i-1]==hypothesis[j-1] and dp[i][j]==dp[i-1][j-1]:
   ops.append(AlignOp(MATCH,i-1,j-1))
   i-=1
   j-=1
  elif i>0 and j>0 and dp[i][j]==dp[i-1][j-1]+substitution_cost:
   ops.append(AlignOp(SUBSTITUTE,i-1,j-1))
   i-=1
   j-=1
  elif i>0 and dp[i][j]==dp[i-1][j]+deletion_cost:
   ops.append(AlignOp(DELETE,i-1,None))
   i-=1
  else:
   ops.append(AlignOp(INSERT,None,j-1))
   j-=1
 ops.reverse()
 return Alignment(distance=dp[n][m],ops=ops)
