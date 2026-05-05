//+------------------------------------------------------------------+
//| SPX500 Full Auto Pullback EA                                      |
//| EMA + impulse pullback strategy converted from backtest.py         |
//| Demo-first. Not financial advice.                                 |
//+------------------------------------------------------------------+
#property strict

#include <Trade/Trade.mqh>

CTrade trade;

// ===== RISK / EXECUTION =====
input double RiskPercent              = 0.5;     // Risk per trade (% balance)
input double StopLossPoints           = 300;     // Stop loss in broker points
input double TakeProfitPoints         = 450;     // Take profit in broker points
input ulong  MagicNumber              = 50001;   // EA identifier
input int    MaxSpreadPoints          = 80;      // Skip entries if spread is above this
input int    SlippagePoints           = 30;      // Max allowed deviation
input int    CooldownBars             = 20;      // Bars to wait after each entry
input int    MaxConsecutiveLosses     = 2;       // Pause after this many losses
input int    LossPauseBars            = 240;     // Pause bars after consecutive-loss trigger
input double MaxDailyLossPercent      = 3.0;     // Stop new entries after daily drawdown

// ===== STRATEGY SETTINGS FROM PYTHON BACKTEST =====
input int    Lookback                 = 24;
input double BreakoutBufferPoints     = 2.0;
input double MinImpulsePoints         = 7.5;
input double MinEmaDistancePoints     = 4.0;
input int    MaxEmaCrosses            = 4;
input double MinRecentRangePoints     = 18.0;
input double MinAtrPoints             = 2.0;
input double MaxAtrPoints             = 14.0;
input double MinBodyRatio             = 0.35;
input double MinEmaSlopePoints        = 0.05;
input bool   EnableSessionFilter      = true;
input int    SessionStartHour         = 13;
input int    SessionEndHour           = 17;

// ===== TRADE MANAGEMENT =====
input bool   EnableBreakEven          = true;
input double BreakEvenPoints          = 300;
input bool   EnableTrailingStop       = true;
input double TrailPoints              = 300;

// ===== INTERNAL STATE =====
datetime lastBarTime = 0;
int      cooldownUntilBar = 0;
int      barCounter = 0;
int      consecutiveLosses = 0;
double   dayStartEquity = 0.0;
int      dayOfYear = -1;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber((int)MagicNumber);
   trade.SetDeviationInPoints(SlippagePoints);
   ResetDailyEquityIfNeeded();
   Print("SPX500 Full Auto Pullback EA loaded. Demo-first. Symbol=", _Symbol, " TF=", EnumToString(_Period));
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnTick()
{
   ResetDailyEquityIfNeeded();
   ManageOpenPosition();

   if(!IsNewBar())
      return;

   barCounter++;

   if(HasOpenPosition())
      return;

   if(barCounter < cooldownUntilBar)
      return;

   if(DailyLossLimitHit())
   {
      Print("Daily loss limit hit. No new entries today.");
      return;
   }

   if(CurrentSpreadPoints() > MaxSpreadPoints)
      return;

   int signal = GetSignal();
   if(signal == 1)
      OpenBuy();
   else if(signal == -1)
      OpenSell();
}

//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime t = iTime(_Symbol, _Period, 0);
   if(t != lastBarTime)
   {
      lastBarTime = t;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
void ResetDailyEquityIfNeeded()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != dayOfYear)
   {
      dayOfYear = dt.day_of_year;
      dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      consecutiveLosses = 0;
   }
}

//+------------------------------------------------------------------+
bool DailyLossLimitHit()
{
   if(MaxDailyLossPercent <= 0 || dayStartEquity <= 0)
      return false;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double maxLossMoney = dayStartEquity * (MaxDailyLossPercent / 100.0);
   return (dayStartEquity - equity) >= maxLossMoney;
}

//+------------------------------------------------------------------+
int CurrentSpreadPoints()
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   return (int)MathRound((ask - bid) / _Point);
}

//+------------------------------------------------------------------+
bool HasOpenPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
int GetSignal()
{
   int needed = MathMax(Lookback + 20, 100);
   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   int copied = CopyRates(_Symbol, _Period, 1, needed, rates); // closed candles only
   if(copied < needed)
      return 0;

   int n = copied;
   MqlRates current = rates[n - 1];
   MqlRates previous = rates[n - 2];

   if(EnableSessionFilter)
   {
      MqlDateTime dt;
      TimeToStruct(current.time, dt);
      if(!(dt.hour >= SessionStartHour && dt.hour < SessionEndHour))
         return 0;
   }

   double closes[];
   ArrayResize(closes, n);
   for(int i = 0; i < n; i++)
      closes[i] = rates[i].close;

   double recentHigh = rates[n - Lookback - 3].high;
   double recentLow  = rates[n - Lookback - 3].low;
   for(int i = n - Lookback - 3; i <= n - 4; i++)
   {
      recentHigh = MathMax(recentHigh, rates[i].high);
      recentLow  = MathMin(recentLow, rates[i].low);
   }

   double recentRange = (recentHigh - recentLow) / _Point;
   double emaFast = Ema(closes, n - 50, n - 1, 10);
   double emaSlow = Ema(closes, n - 80, n - 1, 30);
   double emaSlowPrevious = Ema(closes, n - 86, n - 7, 30);
   double emaSlope = (emaSlow - emaSlowPrevious) / _Point;
   double emaDistance = MathAbs(emaFast - emaSlow) / _Point;
   double impulse = MathAbs(previous.close - rates[n - 6].close) / _Point;
   int crosses = CountEmaCrosses(closes, n - 30, n - 1, emaSlow);
   double atrValue = AtrPoints(rates, n, 14);

   double body = MathAbs(current.close - current.open);
   double candleRange = MathMax(current.high - current.low, _Point);
   double bodyRatio = body / candleRange;

   if(emaDistance < MinEmaDistancePoints) return 0;
   if(crosses > MaxEmaCrosses) return 0;
   if(recentRange < MinRecentRangePoints) return 0;
   if(impulse < MinImpulsePoints) return 0;
   if(atrValue < MinAtrPoints || atrValue > MaxAtrPoints) return 0;
   if(bodyRatio < MinBodyRatio) return 0;

   bool buyBreakout = previous.close > recentHigh + BreakoutBufferPoints * _Point;
   bool buyPullback = current.low <= recentHigh && current.close > recentHigh && current.close > current.open;
   bool buyTrend = emaFast > emaSlow && current.close > emaFast && emaSlope > MinEmaSlopePoints;

   bool sellBreakout = previous.close < recentLow - BreakoutBufferPoints * _Point;
   bool sellPullback = current.high >= recentLow && current.close < recentLow && current.close < current.open;
   bool sellTrend = emaFast < emaSlow && current.close < emaFast && emaSlope < -MinEmaSlopePoints;

   if(buyTrend && buyBreakout && buyPullback)
      return 1;
   if(sellTrend && sellBreakout && sellPullback)
      return -1;

   return 0;
}

//+------------------------------------------------------------------+
double Ema(const double &values[], int fromIndex, int toIndex, int period)
{
   fromIndex = MathMax(fromIndex, 0);
   if(toIndex < fromIndex)
      return 0.0;

   double multiplier = 2.0 / (period + 1.0);
   double ema = values[fromIndex];
   for(int i = fromIndex + 1; i <= toIndex; i++)
      ema = (values[i] - ema) * multiplier + ema;

   return ema;
}

//+------------------------------------------------------------------+
int CountEmaCrosses(const double &closes[], int fromIndex, int toIndex, double emaValue)
{
   int crosses = 0;
   int previousSide = 0;
   fromIndex = MathMax(fromIndex, 0);

   for(int i = fromIndex; i <= toIndex; i++)
   {
      int side = closes[i] > emaValue ? 1 : closes[i] < emaValue ? -1 : 0;
      if(previousSide != 0 && side != 0 && side != previousSide)
         crosses++;
      if(side != 0)
         previousSide = side;
   }

   return crosses;
}

//+------------------------------------------------------------------+
double AtrPoints(const MqlRates &rates[], int n, int period)
{
   if(n < period + 2)
      return 0.0;

   double total = 0.0;
   int start = n - period;
   double previousClose = rates[start - 1].close;

   for(int i = start; i < n; i++)
   {
      double trueRange = MathMax(rates[i].high - rates[i].low,
                         MathMax(MathAbs(rates[i].high - previousClose), MathAbs(rates[i].low - previousClose)));
      total += trueRange;
      previousClose = rates[i].close;
   }

   return (total / period) / _Point;
}

//+------------------------------------------------------------------+
double CalculateLotSize()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * (RiskPercent / 100.0);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(tickValue <= 0 || tickSize <= 0 || lotStep <= 0)
      return minLot;

   double slDistance = StopLossPoints * _Point;
   double riskPerLot = (slDistance / tickSize) * tickValue;
   if(riskPerLot <= 0)
      return minLot;

   double lots = riskMoney / riskPerLot;
   lots = MathFloor(lots / lotStep) * lotStep;
   lots = MathMax(minLot, MathMin(maxLot, lots));

   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
void OpenBuy()
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double sl = ask - StopLossPoints * _Point;
   double tp = ask + TakeProfitPoints * _Point;
   double lots = CalculateLotSize();

   if(trade.Buy(lots, _Symbol, ask, sl, tp, "EMA impulse pullback BUY"))
   {
      cooldownUntilBar = barCounter + CooldownBars;
      Print("BUY opened. Lots=", lots, " SL=", sl, " TP=", tp);
   }
   else
      Print("BUY failed. Retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
void OpenSell()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl = bid + StopLossPoints * _Point;
   double tp = bid - TakeProfitPoints * _Point;
   double lots = CalculateLotSize();

   if(trade.Sell(lots, _Symbol, bid, sl, tp, "EMA impulse pullback SELL"))
   {
      cooldownUntilBar = barCounter + CooldownBars;
      Print("SELL opened. Lots=", lots, " SL=", sl, " TP=", tp);
   }
   else
      Print("SELL failed. Retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
void ManageOpenPosition()
{
   if(!PositionSelect(_Symbol))
      return;

   if((ulong)PositionGetInteger(POSITION_MAGIC) != MagicNumber)
      return;

   ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl = PositionGetDouble(POSITION_SL);
   double tp = PositionGetDouble(POSITION_TP);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double price = type == POSITION_TYPE_BUY ? bid : ask;

   double profitPoints = type == POSITION_TYPE_BUY ? (price - entry) / _Point : (entry - price) / _Point;
   double newSL = sl;

   if(EnableBreakEven && profitPoints >= BreakEvenPoints)
   {
      if(type == POSITION_TYPE_BUY && (sl < entry || sl == 0.0))
         newSL = entry;
      if(type == POSITION_TYPE_SELL && (sl > entry || sl == 0.0))
         newSL = entry;
   }

   if(EnableTrailingStop && profitPoints >= BreakEvenPoints)
   {
      if(type == POSITION_TYPE_BUY)
      {
         double trailSL = price - TrailPoints * _Point;
         if(trailSL > newSL)
            newSL = trailSL;
      }
      else
      {
         double trailSL = price + TrailPoints * _Point;
         if(newSL == 0.0 || trailSL < newSL)
            newSL = trailSL;
      }
   }

   if(newSL != sl && newSL > 0.0)
   {
      if(!trade.PositionModify(_Symbol, newSL, tp))
         Print("PositionModify failed. Retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;

   if(!HistoryDealSelect(trans.deal))
      return;

   string symbol = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   long entryType = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);

   if(symbol != _Symbol || (ulong)magic != MagicNumber || entryType != DEAL_ENTRY_OUT)
      return;

   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);

   if(profit < 0)
      consecutiveLosses++;
   else if(profit > 0)
      consecutiveLosses = 0;

   if(consecutiveLosses >= MaxConsecutiveLosses)
   {
      cooldownUntilBar = MathMax(cooldownUntilBar, barCounter + LossPauseBars);
      Print("Consecutive-loss pause activated for ", LossPauseBars, " bars.");
      consecutiveLosses = 0;
   }
}
//+------------------------------------------------------------------+
