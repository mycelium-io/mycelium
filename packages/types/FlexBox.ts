export enum FLEXBOX {
  ROW_REVERSE = 'rowReverse',
  COLUMN = 'column',
  COLUMN_REVERSE = 'columnReverse',
  START = 'start',
  CENTER = 'center',
  BETWEEN = 'between',
  END = 'end',
  AROUND = 'around',
  EVENLY = 'evenly',
  STRETCH = 'stretch',
  BASELINE = 'baseline',
  ROW = 'row',
  WRAP = 'wrap',
  NO = 'no',
  REVERSE = 'reverse',
}

export type FLEXWRAP = FLEXBOX.WRAP | FLEXBOX.NO | FLEXBOX.REVERSE

export type FLEXPOSITION = FLEXBOX.START | FLEXBOX.END | FLEXBOX.CENTER

export type FLEXJUSTIFY =
  | FLEXPOSITION
  | FLEXBOX.BETWEEN
  | FLEXBOX.AROUND
  | FLEXBOX.EVENLY

export type FLEXCONTENT =
  | FLEXPOSITION
  | FLEXBOX.STRETCH
  | FLEXBOX.AROUND
  | FLEXBOX.BETWEEN

export type FLEXITEMS = FLEXPOSITION | FLEXBOX.STRETCH | FLEXBOX.BASELINE

export type FLEXDIRECTION =
  | FLEXBOX.ROW
  | FLEXBOX.ROW_REVERSE
  | FLEXBOX.COLUMN
  | FLEXBOX.COLUMN_REVERSE
